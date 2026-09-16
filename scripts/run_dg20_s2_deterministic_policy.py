#!/usr/bin/env python3
"""Run DG-20 S2 deterministic recovery on fresh governed PostgreSQL."""

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
from evals.dg15.runtime_session import LocalDG15RuntimeSession
from evals.dg16.lme10 import load_public_dev_cases
from evals.dg20.deterministic_policy_eval import (
    PRODUCT_SCHEMA,
    acquisition_loss_ledger,
    score_s2_product,
    seal_s2_product,
)
from evals.dg20.official_channel_oracle import execution_summary
from milai.api.app import _embedding_provider
from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    AcquisitionRuntimeCapabilityConfig,
    feasible_acquisition_actions,
    resolve_acquisition_capabilities,
    validate_feasible_action,
)
from milai.application.deterministic_recovery import (
    build_acquisition_observation_v02,
    select_deterministic_recovery_action,
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
DEFAULT_S1_RECEIPT = ROOT / "var/dg20/s1/dg20-s1-official-channel-oracle-20260828-003/receipt.json"
DEFAULT_OUTPUT_ROOT = ROOT / "var/dg20/s2"
CANDIDATE_CAP = 8
CONTEXT_TOKENS = 2_048


class DG20S2RunError(RuntimeError):
    """The S2 real-runtime execution failed its fixed product contract."""


def run(
    *,
    run_id: str,
    output_root: Path,
    env_file: Path,
    q1r_archive: Path,
    labels_path: Path,
    s1_receipt_path: Path,
    mcp_concurrency: int,
    projection_batch_size: int,
) -> dict[str, Any]:
    if output_root.exists():
        raise DG20S2RunError("output exists; choose a fresh S2 run ID")
    output_root.mkdir(parents=True)
    plan = {
        "schema": "milai.dg20.s2-plan.v0.1",
        "run_id": run_id,
        "entry_gate": _identity(s1_receipt_path),
        "entry_gate_status": "PASS_S1_OFFICIAL_CHANNEL_ORACLE",
        "mode": "SHADOW_NO_CONTEXT_MUTATION",
        "candidate_cap": CANDIDATE_CAP,
        "context_tokens": CONTEXT_TOKENS,
        "max_extra_passes": 1,
        "provider_calls": 0,
        "automatic_retries": 0,
        "formal_holdout_consumed": False,
    }
    _atomic_json(output_root / "plan.json", plan)
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
    deferred_cleanup: list[tuple[str, Any]] = []
    runtime_start: dict[str, Any] = {}
    runtime_close: dict[str, Any] = {"status": "NOT_STARTED"}
    try:
        runtime_start = dict(session.start(run_id))
        settings = session._settings
        database_urls = session._database_urls
        if settings is None or database_urls is None:
            raise DG20S2RunError("live Runtime settings are unavailable")
        database = Database(settings, dsn=database_urls["api"], expected_role="milai_api")
        repository = RetrievalRepository(database)
        context = SessionContext(settings.tenant_id, settings.local_actor_id)
        embedding = _embedding_provider(settings)
        if embedding.identity.projection_dimensions != 128:
            raise DG20S2RunError("S2 inherited embedding projection is not 128d")
        executor = EvidenceAcquisitionExecutor(repository, embedding)
        policy = AcquisitionCapabilityPolicy(max_candidates=CANDIDATE_CAP)
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
                embedding=embedding,
                policy=policy,
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
                        "stage": "dg20-s2-product",
                        "case": ordinal,
                        "case_count": len(cases),
                        "case_id": case.case_id,
                        "decision": product_case["decision"]["reason_code"],
                        "extra_pass_count": product_case["extra_pass_count"],
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
        "status": "PRODUCT_POLICY_COMPLETE_UNSCORED",
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
            "product_default_changed": False,
            "extra_passes_per_query_max": 1,
        },
        "selection": selection,
        "entry_s1_receipt": _identity(s1_receipt_path),
        "q1r_archive": _identity(q1r_archive),
        "runtime": {"start": runtime_start, "close": runtime_close},
        "case_count": len(product_cases),
        "cases": product_cases,
        "lifecycle": lifecycle,
        "product_wall_ms": round((time.perf_counter() - started) * 1_000, 6),
    }
    sealed_path = output_root / "sealed-product-trace.json"
    seal_s2_product(product, sealed_path)
    return _score_and_receipt(
        run_id=run_id,
        output_root=output_root,
        sealed_path=sealed_path,
        labels_path=labels_path,
        q1r_archive=q1r_archive,
        s1_receipt_path=s1_receipt_path,
        started=started,
        resumption=False,
    )


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
        request, candidate_cap=CANDIDATE_CAP, context_budget=CONTEXT_TOKENS
    )
    query_ir = query_plan.memory_query_ir
    if query_ir is None:
        raise DG20S2RunError("S2 query lacks MemoryQueryIR")
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
    baseline = executor.execute(
        context=context,
        request=request,
        query_plan=query_plan,
        acquisition_plan=baseline_plan,
        capability_set=baseline_capabilities,
        policy=policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=0,
    )
    baseline_summary = execution_summary(baseline, case_id=case.case_id)
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
    state = resolve_requirement_state(
        plan=recovery_plan,
        requirements=query_ir.requirements,
        acquisition_capability_digest=recovery_capabilities.capability_digest,
        candidates=baseline.candidates,
        spans=baseline.spans,
        interpretations=baseline.interpretations,
        bindings=baseline.bindings,
        sufficiency_decision=baseline.sufficiency_decision,
        state_epoch=0,
        memory_query_ir=query_ir,
    )
    actions = feasible_acquisition_actions(
        state,
        recovery_capabilities,
        policy,
        source_observed_range=recovery_plan.global_constraints.source_observed_range,
        valid_anchor_available=bool(baseline.candidates),
        remaining_candidates=CANDIDATE_CAP,
        acquisition_plan=recovery_plan,
    )
    regions = [
        hashlib.sha256(_region(value).encode()).hexdigest()
        for value in _string_list(baseline_summary["candidate_refs"])
    ]
    observation = build_acquisition_observation_v02(
        requirement_state=state,
        capability_set=recovery_capabilities,
        policy=policy,
        probe_dispositions=baseline.probe_dispositions,
        feasible_actions=actions,
        remaining_budget={
            "acquisition_passes": 1,
            "candidate_count": CANDIDATE_CAP,
            "model_calls": 0,
        },
        seen_region_digests=regions,
    )
    decision = select_deterministic_recovery_action(
        requirement_state=state,
        capability_set=recovery_capabilities,
        policy=policy,
        observation=observation,
        feasible_actions=actions,
    )
    selected = decision.selected_action
    proposal_count = int(selected is not None)
    satisfied_target_count = int(
        selected is not None and selected.target_requirement_id in state.satisfied_requirement_ids
    )
    unsupported_proposal_count = int(
        selected is not None
        and not validate_feasible_action(selected, state, recovery_capabilities, policy).accepted
    )
    stale_negative_count = proposal_count
    stale_rejected_count = 0
    unsupported_execution_count = 0
    if selected is not None:
        stale_state = state.model_copy(update={"state_epoch": state.state_epoch + 1})
        stale_rejected_count = int(
            not validate_feasible_action(
                selected, stale_state, recovery_capabilities, policy
            ).accepted
        )
        validation = validate_feasible_action(selected, state, recovery_capabilities, policy)
        if not validation.accepted:
            unsupported_execution_count = 1
            raise DG20S2RunError(f"policy selected unsupported action: {validation.reason_code}")
        final_execution = executor.execute(
            context=context,
            request=request,
            query_plan=query_plan,
            acquisition_plan=recovery_plan,
            capability_set=recovery_capabilities,
            policy=policy,
            mode="SHADOW_NO_CONTEXT_MUTATION",
            state_epoch=1,
            action=selected,
            current_requirement_state=state,
            existing_results=baseline.results,
        )
        final_summary = execution_summary(final_execution, case_id=case.case_id)
        extra_pass_count = 1
    else:
        final_summary = baseline_summary
        extra_pass_count = 0
    identity = embedding.identity
    return {
        "case_id": case.case_id,
        "question_sha256": hashlib.sha256(str(case.question).encode()).hexdigest(),
        "source_snapshot_digest": _case_digest(case),
        "query_ir_digest": recovery_plan.query_ir_digest,
        "baseline_plan_digest": _object_digest(baseline_plan.model_dump(mode="json")),
        "recovery_plan_digest": _object_digest(recovery_plan.model_dump(mode="json")),
        "embedding_identity": {
            "provider": identity.provider,
            "model_id": identity.model_id,
            "source_dimensions": identity.source_dimensions,
            "projection_dimensions": identity.projection_dimensions,
        },
        "baseline_capability_set": baseline_capabilities.model_dump(mode="json"),
        "recovery_capability_set": recovery_capabilities.model_dump(mode="json"),
        "baseline": baseline_summary,
        "runtime_requirement_order": [
            item.slot_id for item in query_ir.requirements if item.required
        ],
        "initial_requirement_state": state.model_dump(mode="json"),
        "feasible_actions": [item.model_dump(mode="json") for item in actions],
        "observation": observation.model_dump(mode="json"),
        "decision": decision.model_dump(mode="json"),
        "proposal_audit": {
            "proposal_count": proposal_count,
            "satisfied_target_count": satisfied_target_count,
            "unsupported_proposal_count": unsupported_proposal_count,
            "unsupported_execution_count": unsupported_execution_count,
            "stale_negative_count": stale_negative_count,
            "stale_rejected_count": stale_rejected_count,
        },
        "final": final_summary,
        "extra_pass_count": extra_pass_count,
        "provider_calls": 0,
        "automatic_retries": 0,
        "canonical_mutation": False,
        "context_mutation_performed": False,
    }


def _score_and_receipt(
    *,
    run_id: str,
    output_root: Path,
    sealed_path: Path,
    labels_path: Path,
    q1r_archive: Path,
    s1_receipt_path: Path,
    started: float,
    resumption: bool,
) -> dict[str, Any]:
    score = score_s2_product(sealed_path, labels_path=labels_path)
    if score.get("run_id") != run_id:
        raise DG20S2RunError("S2 sealed product/run identity mismatch")
    score_path = output_root / "score.json"
    receipt_path = output_root / "receipt.json"
    ledger_path = output_root / "acquisition-loss-ledger.json"
    if score_path.exists() or receipt_path.exists() or ledger_path.exists():
        raise DG20S2RunError("S2 scoring outputs already exist")
    _atomic_json(score_path, score)
    _atomic_json(ledger_path, acquisition_loss_ledger(score))
    receipt = {
        "schema": "milai.dg20.s2-deterministic-policy-receipt.v0.1",
        "status": score["disposition"],
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "provider_calls": 0,
        "automatic_retries": 0,
        "sealed_product_trace": _identity(sealed_path),
        "score": _identity(score_path),
        "acquisition_loss_ledger": _identity(ledger_path),
        "plan": _identity(output_root / "plan.json"),
        "entry_s1_receipt": _identity(s1_receipt_path),
        "q1r_archive": _identity(q1r_archive),
        "hard_gate": score["hard_gate"],
        "metrics": score["metrics"],
        "enter_s4": score["enter_s4"],
        "residual_assist": score["residual_assist"],
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
    labels_path: Path,
    q1r_archive: Path,
    s1_receipt_path: Path,
) -> dict[str, Any]:
    sealed_path = output_root / "sealed-product-trace.json"
    if not sealed_path.is_file():
        raise DG20S2RunError("score-only requires an existing sealed S2 product")
    return _score_and_receipt(
        run_id=run_id,
        output_root=output_root,
        sealed_path=sealed_path,
        labels_path=labels_path,
        q1r_archive=q1r_archive,
        s1_receipt_path=s1_receipt_path,
        started=time.perf_counter(),
        resumption=True,
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DG20S2RunError("expected a string list")
    return list(value)


def _region(source_ref: str) -> str:
    return source_ref.rsplit(":t", 1)[0]


def _case_digest(case: Any) -> str:
    return _object_digest([event.canonical() for event in case.history_events])


def _object_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
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
    parser.add_argument("--s1-receipt", type=Path, default=DEFAULT_S1_RECEIPT)
    parser.add_argument("--mcp-concurrency", type=int, default=4)
    parser.add_argument("--projection-batch-size", type=int, default=64)
    parser.add_argument("--score-only", action="store_true")
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    if args.score_only:
        receipt = score_only(
            run_id=args.run_id,
            output_root=output_root,
            labels_path=args.labels,
            q1r_archive=args.q1r_archive,
            s1_receipt_path=args.s1_receipt,
        )
    else:
        receipt = run(
            run_id=args.run_id,
            output_root=output_root,
            env_file=args.env_file,
            q1r_archive=args.q1r_archive,
            labels_path=args.labels,
            s1_receipt_path=args.s1_receipt,
            mcp_concurrency=args.mcp_concurrency,
            projection_batch_size=args.projection_batch_size,
        )
    receipt_path = output_root / "receipt.json"
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "enter_s4": receipt["enter_s4"],
                "receipt": str(receipt_path),
                "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
