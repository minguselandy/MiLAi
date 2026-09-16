#!/usr/bin/env python3
"""Run DG-20 S4 through the shared service and the actual RetrievalService."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
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
from evals.dg15.milai_mcp_adapter import compact_lme_source_ref
from evals.dg15.runtime_session import LocalDG15RuntimeSession
from evals.dg16.lme10 import load_public_dev_cases
from evals.dg20.official_channel_oracle import execution_summary
from evals.dg20.product_faithful_eval import (
    PRODUCT_SCHEMA,
    canonical_sha256,
    score_s4_product,
    seal_s4_product,
)
from milai.api.app import _embedding_provider
from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    AcquisitionRuntimeCapabilityConfig,
    resolve_acquisition_capabilities,
)
from milai.application.deterministic_recovery import (
    CapabilityConstrainedRecoveryService,
    DeterministicRecoveryResult,
)
from milai.application.evidence_acquisition import (
    OFFICIAL_EXECUTOR_IDENTITY,
    EvidenceAcquisitionExecution,
    EvidenceAcquisitionExecutor,
)
from milai.application.memory_access import MemoryAccessPlan
from milai.application.query_planner import QueryPlanner
from milai.application.retrieval import RetrievalService
from milai.domain import RetrievalRequest
from milai.persistence import Database, SessionContext
from milai.persistence.retrieval_repository import RetrievalRepository

DEFAULT_S2_RECEIPT = ROOT / "var/dg20/s2/dg20-s2-deterministic-policy-20260828-001/receipt.json"
DEFAULT_OUTPUT_ROOT = ROOT / "var/dg20/s4"
CANDIDATE_CAP = 8
CONTEXT_TOKENS = 2_048
DEADLINE_MS = 2_000


class DG20S4RunError(RuntimeError):
    """The product-faithful run could not satisfy its fixed contract."""


def run(
    *,
    run_id: str,
    output_root: Path,
    env_file: Path,
    s2_receipt_path: Path,
    mcp_concurrency: int,
    projection_batch_size: int,
) -> dict[str, Any]:
    if output_root.exists():
        raise DG20S4RunError("output exists; choose a fresh S4 run ID")
    s2_receipt = _load_object(s2_receipt_path)
    if s2_receipt.get("status") != "PASS_S2_DETERMINISTIC_CAPABILITY_POLICY":
        raise DG20S4RunError("S4 entry requires the authoritative passing S2 receipt")
    if s2_receipt.get("residual_assist") != "DISABLED_NOT_NEEDED":
        raise DG20S4RunError("S4 deterministic-only lane was not authorized")
    output_root.mkdir(parents=True)
    plan = {
        "schema": "milai.dg20.s4-plan.v0.1",
        "run_id": run_id,
        "entry_s2_receipt": _identity(s2_receipt_path),
        "execution_order": ["SHADOW_NO_CONTEXT_MUTATION", "PRODUCT"],
        "candidate_flag": "retrieval_deterministic_recovery_enabled",
        "candidate_flag_default": False,
        "residual_assist": "DISABLED_NOT_NEEDED",
        "provider_unavailable_behavior": "DETERMINISTIC_ONLY",
        "invalid_cue_behavior": "DETERMINISTIC_ONLY",
        "max_extra_passes": 1,
        "provider_calls": 0,
        "automatic_retries": 0,
        "formal_holdout_consumed": False,
    }
    _atomic_json(output_root / "plan.json", plan)

    cases, selection = load_public_dev_cases()
    session = LocalDG15RuntimeSession(
        output_root=output_root / "runtime",
        env_file=env_file,
        mcp_concurrency=mcp_concurrency,
        projection_batch_size=projection_batch_size,
        inherit_source_embedding_runtime=True,
        barrier_timeout_ms=30_000,
    )
    started = time.perf_counter()
    database: Database | None = None
    lifecycle: list[dict[str, Any]] = []
    product_cases: list[dict[str, Any]] = []
    deferred_cleanup: list[tuple[str, Any]] = []
    runtime_start: dict[str, Any] = {}
    runtime_close: dict[str, Any] = {"status": "NOT_STARTED"}
    try:
        runtime_start = dict(session.start(run_id))
        settings = session._settings
        database_urls = session._database_urls
        if settings is None or database_urls is None:
            raise DG20S4RunError("live Runtime settings are unavailable")
        database = Database(settings, dsn=database_urls["api"], expected_role="milai_api")
        repository = RetrievalRepository(database)
        context = SessionContext(settings.tenant_id, settings.local_actor_id)
        embedding = _embedding_provider(settings)
        if embedding.identity.projection_dimensions != 128:
            raise DG20S4RunError("S4 inherited embedding projection is not 128d")
        executor = EvidenceAcquisitionExecutor(repository, embedding)
        recovery_service = CapabilityConstrainedRecoveryService(executor)
        policy = AcquisitionCapabilityPolicy(max_candidates=CANDIDATE_CAP)
        baseline_runtime = RetrievalService(repository, embedding=embedding)
        candidate_runtime = RetrievalService(
            repository,
            embedding=embedding,
            deterministic_recovery_enabled=True,
        )
        for ordinal, case in enumerate(cases, start=1):
            case_started = time.perf_counter()
            adapter = session.adapter_for_case(case, lambda text: max(1, (len(text) + 3) // 4))
            deferred_cleanup.append((case.case_id, adapter))
            namespace = adapter.reset(run_id, case.case_id)
            adapter.ingest_many(case.history_events)
            readiness = dict(adapter.finalize())
            product_case = _run_case(
                case=case,
                scope=dict(namespace.scope),
                context=context,
                repository=repository,
                executor=executor,
                recovery_service=recovery_service,
                baseline_runtime=baseline_runtime,
                candidate_runtime=candidate_runtime,
                embedding=embedding,
                policy=policy,
                request_prefix=f"{run_id}-{ordinal:02d}",
            )
            product_cases.append(product_case)
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
                        "stage": "dg20-s4-product",
                        "case": ordinal,
                        "case_count": len(cases),
                        "case_id": case.case_id,
                        "decision": product_case["product"]["decision"]["reason_code"],
                        "extra_pass_count": product_case["product"]["extra_pass_count"],
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
            lifecycle_row = next((item for item in lifecycle if item["case_id"] == case_id), None)
            if lifecycle_row is not None:
                lifecycle_row["cleanup_status"] = cleanup.get("status")
        if database is not None:
            database.close()
        runtime_close = dict(session.close())

    product = {
        "schema": PRODUCT_SCHEMA,
        "status": "PRODUCT_FAITHFUL_COMPLETE_UNSCORED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / PRODUCT_PLANE",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "label_fields_available": False,
        "executor_identity": OFFICIAL_EXECUTOR_IDENTITY,
        "candidate_flag_default": False,
        "candidate_flag_opened_dev": True,
        "residual_assist": "DETERMINISTIC_ONLY",
        "provider_calls": 0,
        "reader_calls": 0,
        "automatic_retries": 0,
        "canonical_mutation": False,
        "selection": selection,
        "entry_s2_receipt": _identity(s2_receipt_path),
        "runtime": {"start": runtime_start, "close": runtime_close},
        "case_count": len(product_cases),
        "cases": product_cases,
        "lifecycle": lifecycle,
        "product_wall_ms": round((time.perf_counter() - started) * 1_000, 6),
    }
    sealed_path = output_root / "sealed-product-trace.json"
    seal_s4_product(product, sealed_path)
    return _score_and_receipt(
        run_id=run_id,
        output_root=output_root,
        sealed_path=sealed_path,
        s2_receipt_path=s2_receipt_path,
        started=started,
        resumption=False,
    )


def _score_and_receipt(
    *,
    run_id: str,
    output_root: Path,
    sealed_path: Path,
    s2_receipt_path: Path,
    started: float,
    resumption: bool,
) -> dict[str, Any]:
    score = score_s4_product(sealed_path)
    if score.get("run_id") != run_id:
        raise DG20S4RunError("S4 sealed product/run identity mismatch")
    score_path = output_root / "score.json"
    receipt_path = output_root / "receipt.json"
    if score_path.exists() or receipt_path.exists():
        raise DG20S4RunError("S4 scoring outputs already exist")
    _atomic_json(score_path, score)
    receipt = {
        "schema": "milai.dg20.s4-product-faithful-receipt.v0.1",
        "status": score["disposition"],
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "candidate_flag_default": False,
        "provider_calls": 0,
        "automatic_retries": 0,
        "plan": _identity(output_root / "plan.json"),
        "sealed_product_trace": _identity(sealed_path),
        "score": _identity(score_path),
        "entry_s2_receipt": _identity(s2_receipt_path),
        "hard_gate": score["hard_gate"],
        "metrics": score["metrics"],
        "enter_s5": score["enter_s5"],
        "resumption": {
            "score_only": resumption,
            "sealed_product_rewritten": False,
        },
        "experiment_wall_ms": round((time.perf_counter() - started) * 1_000, 6),
    }
    _atomic_json(receipt_path, receipt)
    return receipt


def score_only(
    *,
    run_id: str,
    output_root: Path,
    s2_receipt_path: Path,
) -> dict[str, Any]:
    sealed_path = output_root / "sealed-product-trace.json"
    if not sealed_path.is_file():
        raise DG20S4RunError("score-only requires an existing sealed S4 product")
    return _score_and_receipt(
        run_id=run_id,
        output_root=output_root,
        sealed_path=sealed_path,
        s2_receipt_path=s2_receipt_path,
        started=time.perf_counter(),
        resumption=True,
    )


def _run_case(
    *,
    case: Any,
    scope: dict[str, Any],
    context: SessionContext,
    repository: RetrievalRepository,
    executor: EvidenceAcquisitionExecutor,
    recovery_service: CapabilityConstrainedRecoveryService,
    baseline_runtime: RetrievalService,
    candidate_runtime: RetrievalService,
    embedding: Any,
    policy: AcquisitionCapabilityPolicy,
    request_prefix: str,
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
        limit=CANDIDATE_CAP,
    )
    access_plan = MemoryAccessPlan(
        access_intent="REQUIRED",
        candidate_cap=CANDIDATE_CAP,
        deadline_ms=DEADLINE_MS,
        context_token_budget=CONTEXT_TOKENS,
        reranker_candidate_cap=CANDIDATE_CAP,
        hard_partitions=("tenant", "principal_scope", "project_scope", "valid_time"),
    )
    query_plan = QueryPlanner().plan(
        request,
        context_budget=CONTEXT_TOKENS,
        candidate_cap=CANDIDATE_CAP,
        deadline_ms=DEADLINE_MS,
        reranker_candidate_cap=CANDIDATE_CAP,
        hard_partitions=access_plan.hard_partitions,
        vector_policy=access_plan.vector_policy,
        reranker_policy=access_plan.reranker_policy,
        access_intent=access_plan.access_intent,
    )
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
    recovery_plan = compile_acquisition_plan(
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
    baseline_capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(
            embedding_projection_dimensions=embedding.identity.projection_dimensions
        ),
        projection_state=projection_state,
        repository=repository,
        policy=policy,
        generated_at=reference_time,
        source_observed_range=baseline_plan.global_constraints.source_observed_range,
        event_occurrence_range=baseline_plan.global_constraints.event_occurrence_range,
    )
    recovery_capabilities = resolve_acquisition_capabilities(
        config=AcquisitionRuntimeCapabilityConfig(
            lexical_enrichment_bound=True,
            lexical_enrichment_enabled=True,
            evidence_dense_enabled=True,
            embedding_projection_dimensions=embedding.identity.projection_dimensions,
        ),
        projection_state=projection_state,
        repository=repository,
        policy=policy,
        generated_at=reference_time,
        source_observed_range=recovery_plan.global_constraints.source_observed_range,
        event_occurrence_range=recovery_plan.global_constraints.event_occurrence_range,
    )
    baseline_shadow = executor.execute(
        context=context,
        request=request,
        query_plan=query_plan,
        acquisition_plan=baseline_plan,
        capability_set=baseline_capabilities,
        policy=policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=0,
    )
    baseline_product = executor.execute(
        context=context,
        request=request,
        query_plan=query_plan,
        acquisition_plan=baseline_plan,
        capability_set=baseline_capabilities,
        policy=policy,
        mode="PRODUCT",
        state_epoch=0,
    )
    shadow = recovery_service.recover(
        context=context,
        request=request,
        query_plan=query_plan,
        recovery_plan=recovery_plan,
        capability_set=recovery_capabilities,
        policy=policy,
        baseline_execution=baseline_shadow,
        mode="SHADOW_NO_CONTEXT_MUTATION",
    )
    product = recovery_service.recover(
        context=context,
        request=request,
        query_plan=query_plan,
        recovery_plan=recovery_plan,
        capability_set=recovery_capabilities,
        policy=policy,
        baseline_execution=baseline_product,
        mode="PRODUCT",
    )
    baseline_execution = baseline_runtime.retrieve(
        context,
        request,
        f"{request_prefix}-baseline",
        access_plan=access_plan,
    )
    candidate_execution = candidate_runtime.retrieve(
        context,
        request,
        f"{request_prefix}-candidate",
        access_plan=access_plan,
    )
    baseline_view = _runtime_view(baseline_execution.body)
    candidate_view = _runtime_view(candidate_execution.body)
    shadow_view = _recovery_view(shadow, baseline_shadow, case.case_id)
    product_view = _recovery_view(product, baseline_product, case.case_id)
    ineligible_changed = (
        baseline_view["business_output_digest"] != candidate_view["business_output_digest"]
        if product.decision.selected_action is None
        else False
    )
    return {
        "case_id": case.case_id,
        "question_sha256": hashlib.sha256(str(case.question).encode()).hexdigest(),
        "source_snapshot_digest": canonical_sha256(
            [event.canonical() for event in case.history_events]
        ),
        "query_ir_digest": recovery_plan.query_ir_digest,
        "baseline": execution_summary(baseline_product, case_id=case.case_id),
        "shadow": shadow_view,
        "product": product_view,
        "runtime_baseline": baseline_view,
        "runtime_candidate": candidate_view,
        "ineligible_product_output_changed": ineligible_changed,
        "product_shadow_candidate_identity": (
            shadow_view["final"]["candidate_refs"] == product_view["final"]["candidate_refs"]
        ),
        "runtime_product_candidate_identity": (
            candidate_view["evidence_source_refs"] == product_view["final"]["candidate_refs"]
        ),
    }


def _recovery_view(
    result: DeterministicRecoveryResult,
    baseline: EvidenceAcquisitionExecution,
    case_id: str,
) -> dict[str, Any]:
    final = result.final_execution or baseline
    return {
        "initial_requirement_state": result.initial_requirement_state.model_dump(mode="json"),
        "observation": result.observation.model_dump(mode="json"),
        "decision": result.decision.model_dump(mode="json"),
        "final": execution_summary(final, case_id=case_id),
        "extra_pass_count": result.extra_pass_count,
        "provider_calls": result.provider_calls,
        "automatic_retries": result.automatic_retries,
        "canonical_mutation": result.canonical_mutation,
    }


def _runtime_view(body: dict[str, Any]) -> dict[str, Any]:
    progressive = _object(body.get("progressive_l1"))
    results = body.get("results")
    if not isinstance(results, list):
        raise DG20S4RunError("RetrievalService response lacks results")
    evidence = [
        item
        for item in results
        if isinstance(item, dict) and isinstance(item.get("evidence_id"), str)
    ]
    evidence_refs = [compact_lme_source_ref(str(item.get("source_ref", ""))) for item in evidence]
    business_output = {
        "results": results,
        "derived_result": body.get("derived_result"),
        "abstained": body.get("abstained"),
        "abstention_reason": body.get("abstention_reason"),
        "fallback_used": body.get("fallback_used"),
        "fallback_reason": body.get("fallback_reason"),
    }
    recovery = progressive.get("deterministic_recovery")
    if recovery is None:
        recovery = {
            "enabled": False,
            "decision": None,
            "extra_pass_count": 0,
            "provider_calls": 0,
            "automatic_retries": 0,
            "canonical_mutation": False,
        }
    return {
        "status_code": 200,
        "business_output_digest": canonical_sha256(business_output),
        "evidence_source_refs": evidence_refs,
        "evidence_result_count": len(evidence),
        "recovery": recovery,
        "acquisition_state": progressive.get("acquisition_state"),
        "abstained": body.get("abstained"),
        "abstention_reason": body.get("abstention_reason"),
        "canonical_mutation": False,
    }


def _load_object(path: Path) -> dict[str, Any]:
    return _object(json.loads(path.read_text(encoding="utf-8")))


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DG20S4RunError("expected object")
    return value


def _identity(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--s2-receipt", type=Path, default=DEFAULT_S2_RECEIPT)
    parser.add_argument("--mcp-concurrency", type=int, default=4)
    parser.add_argument("--projection-batch-size", type=int, default=64)
    parser.add_argument("--score-only", action="store_true")
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    if args.score_only:
        receipt = score_only(
            run_id=args.run_id,
            output_root=output_root,
            s2_receipt_path=args.s2_receipt,
        )
    else:
        receipt = run(
            run_id=args.run_id,
            output_root=output_root,
            env_file=args.env_file,
            s2_receipt_path=args.s2_receipt,
            mcp_concurrency=args.mcp_concurrency,
            projection_batch_size=args.projection_batch_size,
        )
    receipt_path = output_root / "receipt.json"
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "enter_s5": receipt["enter_s5"],
                "receipt": str(receipt_path),
                "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
