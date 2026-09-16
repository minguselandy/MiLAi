#!/usr/bin/env python3
"""Run DG-20 S5 as a same-snapshot matched Runtime/Reader A/B evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
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
from evals.dg14.provider import (
    MatchedVllmProvider,
    full_provider_contract,
    full_provider_contract_sha256,
)
from evals.dg15.milai_mcp_adapter import compact_lme_source_ref
from evals.dg15.runtime_session import LocalDG15RuntimeSession
from evals.dg16.lme10 import load_public_dev_cases
from evals.dg20.matched_q6_eval import (
    ARM_A,
    ARM_B,
    ARMS,
    BUDGETS,
    PRODUCT_SCHEMA,
    canonical_sha256,
    score_s5_product,
    seal_s5_product,
)
from evals.paper.provider import MODEL_ID
from milai.api.app import _embedding_provider
from milai.application.memory_context import MemoryContextCompiler
from milai.application.memory_resolve import MemoryResolveService
from milai.application.retrieval import RetrievalService
from milai.domain.memory_resolve import MemoryResolveBudget, MemoryResolveRequest
from milai.persistence import Database, SessionContext
from milai.persistence.retrieval_repository import RetrievalRepository

from scripts.run_dg16_q6 import _process_identity, _provider_record, _reader_models

DEFAULT_S2_RECEIPT = ROOT / "var/dg20/s2/dg20-s2-deterministic-policy-20260828-002/receipt.json"
DEFAULT_S4_RECEIPT = ROOT / "var/dg20/s4/dg20-s4-product-faithful-20260828-002/receipt.json"
DEFAULT_DG17_BASELINE = ROOT / "var/dg17/q6/dg17-q6-sealed-20260827-003/receipt.json"
DEFAULT_DG19_BASELINE = ROOT / "var/dg19/terminal/dg19-terminal-20260828-001/receipt.json"
DEFAULT_OUTPUT_ROOT = ROOT / "var/dg20/s5"
CANDIDATE_CAP = 8
DEADLINE_MS = 2_000
_COMPACT_SOURCE_REF = re.compile(r"^[^:]+:s\d+:([^:]+):t\d+$")


class DG20S5RunError(RuntimeError):
    """The S5 entry gate, product plane, or matched identity failed."""


def run(
    *,
    run_id: str,
    output_root: Path,
    env_file: Path,
    s2_receipt_path: Path,
    s4_receipt_path: Path,
    dg17_baseline_path: Path,
    dg19_baseline_path: Path,
    reader_url: str,
    mcp_concurrency: int,
    projection_batch_size: int,
) -> dict[str, Any]:
    if output_root.exists():
        raise DG20S5RunError("output exists; choose a fresh S5 run ID")
    s2_receipt = _load_object(s2_receipt_path)
    s4_receipt = _load_object(s4_receipt_path)
    if s2_receipt.get("status") != "PASS_S2_DETERMINISTIC_CAPABILITY_POLICY":
        raise DG20S5RunError("S5 requires the authoritative passing S2 receipt")
    if (
        s4_receipt.get("status") != "PASS_S4_ONE_PASS_PRODUCT_FAITHFUL_INTEGRATION"
        or s4_receipt.get("enter_s5") is not True
    ):
        raise DG20S5RunError("S5 entry requires the authoritative passing S4 receipt")
    if s2_receipt.get("residual_assist") != "DISABLED_NOT_NEEDED":
        raise DG20S5RunError("S5 two-arm lane requires residual assist to be unnecessary")
    output_root.mkdir(parents=True)
    started = time.perf_counter()
    plan = {
        "schema": "milai.dg20.s5-plan.v0.1",
        "run_id": run_id,
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / MATCHED_PRODUCT_EVALUATION",
        "entry_s2_receipt": _identity(s2_receipt_path),
        "entry_s4_receipt": _identity(s4_receipt_path),
        "historical_baselines": {
            "dg17": _identity(dg17_baseline_path),
            "dg19": _identity(dg19_baseline_path),
        },
        "arms": list(ARMS),
        "arm_c": "NOT_APPLICABLE_RESIDUAL_ASSIST_DISABLED_NOT_NEEDED",
        "token_budgets": list(BUDGETS),
        "candidate_cap": CANDIDATE_CAP,
        "deadline_ms": DEADLINE_MS,
        "same_opened_dev_snapshot": True,
        "same_query_ir_compiler": True,
        "same_runtime_context_compiler": True,
        "same_reader_model_prompt_generation": True,
        "same_scorer": True,
        "same_case_order": True,
        "same_operator_sufficiency_identity": True,
        "provider_seed_policy": "ARM_INDEPENDENT_RUN_CASE_BUDGET",
        "residual_assist": "DISABLED_NOT_NEEDED",
        "automatic_retries": 0,
        "formal_holdout_consumed": False,
    }
    _atomic_json(output_root / "plan.json", plan)

    cases, selection = load_public_dev_cases()
    provider = MatchedVllmProvider(reader_url)
    session = LocalDG15RuntimeSession(
        output_root=output_root / "runtime",
        env_file=env_file,
        mcp_concurrency=mcp_concurrency,
        projection_batch_size=projection_batch_size,
        inherit_source_embedding_runtime=True,
        barrier_timeout_ms=30_000,
    )
    database: Database | None = None
    runtime_start: dict[str, Any] = {}
    runtime_close: dict[str, Any] = {"status": "NOT_STARTED"}
    lifecycle: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    deferred_cleanup: list[tuple[str, Any]] = []
    reader_ordinal = 0
    try:
        runtime_start = dict(session.start(run_id))
        settings = session._settings
        database_urls = session._database_urls
        if settings is None or database_urls is None:
            raise DG20S5RunError("live Runtime settings are unavailable")
        database = Database(settings, dsn=database_urls["api"], expected_role="milai_api")
        repository = RetrievalRepository(database)
        session_context = SessionContext(settings.tenant_id, settings.local_actor_id)
        embedding = _embedding_provider(settings)
        compiler = MemoryContextCompiler(repository)
        baseline = MemoryResolveService(
            RetrievalService(repository, embedding=embedding),
            context_compiler=compiler,
        )
        candidate = MemoryResolveService(
            RetrievalService(
                repository,
                embedding=embedding,
                deterministic_recovery_enabled=True,
            ),
            context_compiler=compiler,
        )
        resolvers = {ARM_A: baseline, ARM_B: candidate}

        for case_ordinal, case in enumerate(cases, start=1):
            case_started = time.perf_counter()
            adapter = session.adapter_for_case(
                case, lambda text: max(1, (len(text.encode("utf-8")) + 2) // 3)
            )
            deferred_cleanup.append((case.case_id, adapter))
            namespace = adapter.reset(run_id, case.case_id)
            adapter.ingest_many(case.history_events)
            readiness = dict(adapter.finalize())
            if readiness.get("status") != "READY":
                raise DG20S5RunError(f"case {case.case_id} projection was not READY")
            scope = dict(namespace.scope)
            source_snapshot_digest = canonical_sha256(
                [event.canonical() for event in case.history_events]
            )
            case_records: list[dict[str, Any]] = []
            for budget in BUDGETS:
                for arm in ARMS:
                    reader_ordinal += 1
                    record = _run_cell(
                        resolver=resolvers[arm],
                        provider=provider,
                        arm=arm,
                        run_id=run_id,
                        request_id=(f"{run_id}-{case_ordinal:02d}-{budget}-{arm[0].lower()}"),
                        reader_ordinal=reader_ordinal,
                        case=case,
                        budget=budget,
                        scope=scope,
                        session_context=session_context,
                        source_snapshot_digest=source_snapshot_digest,
                    )
                    records.append(record)
                    case_records.append(record)
            _assert_case_pairing(case_records, case.case_id, source_snapshot_digest)
            lifecycle.append(
                {
                    "case_id": case.case_id,
                    "case_ordinal": case_ordinal,
                    "source_turn_count": len(case.history_events),
                    "source_snapshot_digest": source_snapshot_digest,
                    "readiness_status": readiness.get("status"),
                    "cleanup_status": "DEFERRED_UNTIL_PRODUCT_SEAL",
                    "product_record_count": len(case_records),
                    "wall_ms": round((time.perf_counter() - case_started) * 1_000, 6),
                }
            )
            print(
                json.dumps(
                    {
                        "stage": "dg20-s5-matched-reader",
                        "case": case_ordinal,
                        "case_count": len(cases),
                        "case_id": case.case_id,
                        "records": len(case_records),
                        "reader_calls": reader_ordinal,
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
            row = next((value for value in lifecycle if value["case_id"] == case_id), None)
            if row is not None:
                row["cleanup_status"] = cleanup.get("status")
        if database is not None:
            database.close()
        runtime_close = dict(session.close())

    if len(records) != 40 or reader_ordinal != 40:
        raise DG20S5RunError("S5 product/Reader denominator drifted")
    if runtime_close.get("status") != "PASS":
        raise DG20S5RunError("S5 isolated Runtime did not close cleanly")
    product = {
        "schema": PRODUCT_SCHEMA,
        "status": "PRODUCT_AND_READER_COMPLETE_UNSCORED",
        "run_id": run_id,
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / PRODUCT_PLANE",
        "formal_holdout_consumed": False,
        "formal_source_id_overlap": [],
        "labels_loaded": False,
        "label_fields_available": False,
        "selection": selection,
        "arms": list(ARMS),
        "arm_c": "NOT_APPLICABLE_RESIDUAL_ASSIST_DISABLED_NOT_NEEDED",
        "runtime_context_owner": "MemoryContextCompiler",
        "eval_context_selection_rules": 0,
        "reader_model_id": MODEL_ID,
        "provider_contract": full_provider_contract(),
        "provider_contract_sha256": full_provider_contract_sha256(),
        "reader_identity": {
            "url": reader_url,
            "models": _reader_models(reader_url),
            "process": _process_identity(7860),
        },
        "runtime": {"start": runtime_start, "close": runtime_close},
        "record_count": len(records),
        "reader_calls": reader_ordinal,
        "residual_provider_calls": 0,
        "automatic_retries": 0,
        "canonical_mutation": False,
        "records": records,
        "lifecycle": lifecycle,
        "product_wall_ms": round((time.perf_counter() - started) * 1_000, 6),
    }
    sealed_path = output_root / "sealed-product-trace.json"
    seal_s5_product(product, sealed_path)

    # This is the only point at which opened-development scorer truth is loaded.
    score, loss_ledger = score_s5_product(
        sealed_path,
        s2_receipt=s2_receipt,
        s4_receipt=s4_receipt,
    )
    score_path = output_root / "score.json"
    loss_path = output_root / "acquisition-loss-ledger.json"
    _atomic_json(score_path, score)
    _atomic_json(loss_path, loss_ledger)
    receipt = {
        "schema": "milai.dg20.s5-matched-q6-receipt.v0.1",
        "status": score["disposition"],
        "core_disposition": score["disposition"],
        "residual_assist": "DISABLED_NOT_NEEDED",
        "run_id": run_id,
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / MATCHED_EVALUATION",
        "formal_holdout_consumed": False,
        "plan": _identity(output_root / "plan.json"),
        "sealed_product_trace": _identity(sealed_path),
        "score": _identity(score_path),
        "acquisition_loss_ledger": _identity(loss_path),
        "entry_s2_receipt": _identity(s2_receipt_path),
        "entry_s4_receipt": _identity(s4_receipt_path),
        "hard_gate": score["hard_gate"],
        "comparisons": score["comparisons"],
        "state_correctness": score["state_correctness"],
        "safety_and_cost": score["safety_and_cost"],
        "labels_loaded_only_after_product_seal": True,
        "reader_model_id": MODEL_ID,
        "provider_contract_sha256": full_provider_contract_sha256(),
        "experiment_wall_ms": round((time.perf_counter() - started) * 1_000, 6),
    }
    _atomic_json(output_root / "receipt.json", receipt)
    return receipt


def rescore_sealed(
    *,
    run_id: str,
    output_root: Path,
    sealed_source: Path,
    s2_receipt_path: Path,
    s4_receipt_path: Path,
) -> dict[str, Any]:
    """Create a fresh score-only receipt without rewriting sealed product facts."""

    if output_root.exists():
        raise DG20S5RunError("output exists; choose a fresh S5 score-only run ID")
    s2_receipt = _load_object(s2_receipt_path)
    s4_receipt = _load_object(s4_receipt_path)
    product = _load_object(sealed_source)
    if (
        product.get("schema") != PRODUCT_SCHEMA
        or product.get("labels_loaded") is not False
        or product.get("formal_holdout_consumed") is not False
        or product.get("record_count") != 40
    ):
        raise DG20S5RunError("score-only source is not a sealed S5 product")
    output_root.mkdir(parents=True)
    started = time.perf_counter()
    plan = {
        "schema": "milai.dg20.s5-score-only-plan.v0.1",
        "run_id": run_id,
        "source_product_run_id": product.get("run_id"),
        "source_sealed_product": _identity(sealed_source),
        "entry_s2_receipt": _identity(s2_receipt_path),
        "entry_s4_receipt": _identity(s4_receipt_path),
        "reason": (
            "SCORER_ADAPTER_CORRECTION_OFFICIAL_DERIVED_OPERANDS_AND_IDENTICAL_PROMPT_MATCHING"
        ),
        "product_rerun": False,
        "reader_rerun": False,
        "sealed_product_rewritten": False,
        "scorer_truth_loaded_only_after_local_seal_copy": True,
        "formal_holdout_consumed": False,
    }
    _atomic_json(output_root / "plan.json", plan)
    local_sealed = output_root / "sealed-product-trace.json"
    shutil.copyfile(sealed_source, local_sealed)
    if (
        hashlib.sha256(local_sealed.read_bytes()).digest()
        != hashlib.sha256(sealed_source.read_bytes()).digest()
    ):
        raise DG20S5RunError("score-only sealed product copy identity drifted")
    score, loss_ledger = score_s5_product(
        local_sealed,
        s2_receipt=s2_receipt,
        s4_receipt=s4_receipt,
    )
    score_path = output_root / "score.json"
    loss_path = output_root / "acquisition-loss-ledger.json"
    _atomic_json(score_path, score)
    _atomic_json(loss_path, loss_ledger)
    receipt = {
        "schema": "milai.dg20.s5-matched-q6-rescore-receipt.v0.1",
        "status": score["disposition"],
        "core_disposition": score["disposition"],
        "residual_assist": "DISABLED_NOT_NEEDED",
        "run_id": run_id,
        "source_product_run_id": product.get("run_id"),
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / MATCHED_EVALUATION",
        "formal_holdout_consumed": False,
        "plan": _identity(output_root / "plan.json"),
        "source_sealed_product": _identity(sealed_source),
        "sealed_product_trace": _identity(local_sealed),
        "score": _identity(score_path),
        "acquisition_loss_ledger": _identity(loss_path),
        "entry_s2_receipt": _identity(s2_receipt_path),
        "entry_s4_receipt": _identity(s4_receipt_path),
        "hard_gate": score["hard_gate"],
        "comparisons": score["comparisons"],
        "state_correctness": score["state_correctness"],
        "safety_and_cost": score["safety_and_cost"],
        "reader_pairing": score["reader_pairing"],
        "product_rerun": False,
        "reader_rerun": False,
        "sealed_product_rewritten": False,
        "labels_loaded_only_after_product_seal": True,
        "experiment_wall_ms": round((time.perf_counter() - started) * 1_000, 6),
    }
    _atomic_json(output_root / "receipt.json", receipt)
    return receipt


def _run_cell(
    *,
    resolver: MemoryResolveService,
    provider: MatchedVllmProvider,
    arm: str,
    run_id: str,
    request_id: str,
    reader_ordinal: int,
    case: Any,
    budget: int,
    scope: dict[str, Any],
    session_context: SessionContext,
    source_snapshot_digest: str,
) -> dict[str, Any]:
    reference_time = datetime.fromisoformat(
        normalize_lme_timestamp(str(case.question_at)).replace("Z", "+00:00")
    )
    request = MemoryResolveRequest(
        query=str(case.question),
        requested_scope=scope,
        required_authority="INFORMATIONAL",
        required_freshness="CURRENT",
        consistency_mode="CANONICAL_REQUIRED",
        reference_time=reference_time,
        budget=MemoryResolveBudget(
            max_results=CANDIDATE_CAP,
            max_candidates=CANDIDATE_CAP,
            max_context_tokens=budget,
            max_latency_ms=DEADLINE_MS,
        ),
    )
    query_started = time.perf_counter()
    execution = resolver.resolve(session_context, request, request_id)
    query_ms = (time.perf_counter() - query_started) * 1_000
    body = execution.body
    if execution.status_code != 200 or body.get("status") not in {
        "HIT",
        "PARTIAL",
        "CONTESTED",
        "ABSENT",
        "ABSTAINED",
    }:
        raise DG20S5RunError(f"case {case.case_id}/{arm}/{budget} returned unusable Runtime status")
    memory_context = _object(body.get("memory_context"), "Runtime MemoryContext")
    context = memory_context.get("text")
    if not isinstance(context, str) or not context:
        raise DG20S5RunError("Runtime MemoryContext is empty")
    items = body.get("items")
    evidence_items = (
        [dict(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    )
    source_refs = _source_refs(evidence_items)
    selected_raw = memory_context.get("selected_source_turn_refs")
    selected_refs = (
        [
            compact_lme_source_ref(str(value))
            for value in selected_raw
            if isinstance(selected_raw, list) and isinstance(value, str)
        ]
        if isinstance(selected_raw, list)
        else []
    )
    answer = provider.answer(
        run_id=run_id,
        case_id=str(case.case_id),
        method_id=arm,
        question=str(case.question),
        question_as_of=str(case.question_at),
        memory_context=context,
        token_budget=budget,
    )
    if answer.context != context or answer.context_truncated:
        raise DG20S5RunError("Reader modified a Runtime-owned S5 context")
    search_trace = _object(body.get("search_trace"), "Runtime search trace")
    raw_recovery = search_trace.get("deterministic_recovery")
    recovery = (
        dict(raw_recovery)
        if isinstance(raw_recovery, dict)
        else {
            "enabled": False,
            "attempted": False,
            "decision": None,
            "extra_pass_count": 0,
            "provider_calls": 0,
            "automatic_retries": 0,
            "canonical_mutation": False,
        }
    )
    retrieval_trace = [
        {
            "rank": rank,
            "source_id": source_ref,
            "session_id": _session_id(source_ref),
        }
        for rank, source_ref in enumerate(source_refs, start=1)
    ]
    return {
        "case_id": str(case.case_id),
        "category": str(case.category),
        "arm": arm,
        "method_id": arm,
        "token_budget": budget,
        "request_id": request_id,
        "reader_call_ordinal": reader_ordinal,
        "status": body.get("status"),
        "query_latency_ms": round(query_ms, 6),
        "source_snapshot_digest": source_snapshot_digest,
        "context": context,
        "context_sha256": hashlib.sha256(context.encode("utf-8")).hexdigest(),
        "context_tokens": int(memory_context.get("estimated_tokens", 0)),
        "semantic_context_digest": memory_context.get("semantic_context_digest"),
        "reader_context_digest": memory_context.get("reader_context_digest"),
        "selected_source_refs": selected_refs,
        "all_source_refs": source_refs,
        "retrieval_trace": retrieval_trace,
        "evidence_items": evidence_items,
        "derived_result": body.get("derived_result"),
        "sufficiency_decision": body.get("sufficiency_decision"),
        "search_trace": search_trace,
        "memory_query_ir": body.get("memory_query_ir"),
        "recovery": recovery,
        "usage": {
            "retrieval_logical_calls": 1,
            "additional_acquisition_calls": _int_or_zero(recovery.get("extra_pass_count")),
            "residual_provider_calls": _int_or_zero(recovery.get("provider_calls")),
            "automatic_retries": _int_or_zero(recovery.get("automatic_retries")),
            "controller_tokens": 0,
        },
        "answer": answer.answer,
        "provider": _provider_record(answer),
    }


def _assert_case_pairing(records: list[dict[str, Any]], case_id: str, snapshot_digest: str) -> None:
    if len(records) != 4:
        raise DG20S5RunError(f"case {case_id} matched cell denominator drifted")
    observed = {(row["arm"], row["token_budget"]) for row in records}
    expected = {(arm, budget) for arm in ARMS for budget in BUDGETS}
    if observed != expected or any(
        row["source_snapshot_digest"] != snapshot_digest for row in records
    ):
        raise DG20S5RunError(f"case {case_id} did not use one immutable snapshot")
    for budget in BUDGETS:
        pair = [row for row in records if row["token_budget"] == budget]
        seeds = {int(row["provider"]["seed"]) for row in pair}
        if len(seeds) != 1:
            raise DG20S5RunError(f"case {case_id}/{budget} Reader seed was not matched")


def _source_refs(items: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for item in items:
        source = item.get("source_ref")
        if isinstance(source, str):
            compact = compact_lme_source_ref(source)
            if compact not in refs:
                refs.append(compact)
    return refs


def _session_id(source_ref: str) -> str | None:
    matched = _COMPACT_SOURCE_REF.match(source_ref)
    return matched.group(1) if matched is not None else None


def _int_or_zero(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _load_object(path: Path) -> dict[str, Any]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), str(path))
    except (OSError, json.JSONDecodeError) as exc:
        raise DG20S5RunError(f"invalid bound JSON artifact: {path}") from exc


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DG20S5RunError(f"{name} must be an object")
    return value


def _identity(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise DG20S5RunError(f"bound artifact is absent: {path}")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _failure_ledger(output_root: Path, run_id: str, exc: BaseException) -> None:
    if not output_root.exists():
        return
    path = output_root / "failure-ledger.json"
    if path.exists():
        return
    _atomic_json(
        path,
        {
            "schema": "milai.dg20.failure-ledger.v0.1",
            "run_id": run_id,
            "status": "FAILED_PRESERVED_FOR_DIAGNOSIS",
            "failure_type": type(exc).__name__,
            "reason": str(exc),
            "sealed_product_present": (output_root / "sealed-product-trace.json").is_file(),
            "automatic_retry_attempted": False,
            "formal_holdout_consumed": False,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--s2-receipt", type=Path, default=DEFAULT_S2_RECEIPT)
    parser.add_argument("--s4-receipt", type=Path, default=DEFAULT_S4_RECEIPT)
    parser.add_argument("--dg17-baseline", type=Path, default=DEFAULT_DG17_BASELINE)
    parser.add_argument("--dg19-baseline", type=Path, default=DEFAULT_DG19_BASELINE)
    parser.add_argument("--reader-url", default="http://127.0.0.1:7860")
    parser.add_argument("--rescore-sealed", type=Path)
    parser.add_argument("--mcp-concurrency", type=int, default=4)
    parser.add_argument("--projection-batch-size", type=int, default=64)
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    try:
        if args.rescore_sealed is not None:
            receipt = rescore_sealed(
                run_id=args.run_id,
                output_root=output_root,
                sealed_source=args.rescore_sealed,
                s2_receipt_path=args.s2_receipt,
                s4_receipt_path=args.s4_receipt,
            )
        else:
            receipt = run(
                run_id=args.run_id,
                output_root=output_root,
                env_file=args.env_file,
                s2_receipt_path=args.s2_receipt,
                s4_receipt_path=args.s4_receipt,
                dg17_baseline_path=args.dg17_baseline,
                dg19_baseline_path=args.dg19_baseline,
                reader_url=args.reader_url,
                mcp_concurrency=args.mcp_concurrency,
                projection_batch_size=args.projection_batch_size,
            )
    except BaseException as exc:
        _failure_ledger(output_root, args.run_id, exc)
        raise
    receipt_path = output_root / "receipt.json"
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "residual_assist": receipt["residual_assist"],
                "receipt": str(receipt_path),
                "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                "hostname": platform.node(),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["status"] == "PASS_REQUIREMENT_STATE_ALIGNED_ACQUISITION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
