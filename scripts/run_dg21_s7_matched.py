#!/usr/bin/env python3
"""Run the frozen product-first DG-21 four-arm matched evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
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
    full_provider_contract_sha256,
    logical_request_id,
    matched_seed,
)
from evals.dg15.milai_mcp_adapter import compact_lme_source_ref
from evals.dg15.runtime_session import LocalDG15RuntimeSession
from evals.dg16.lme10 import load_public_dev_cases
from evals.dg20.matched_q6_eval import _matched_causal_reader_records
from evals.dg21.matched_eval import (
    ARM_A,
    ARM_B,
    ARM_C,
    ARM_D,
    ARMS,
    BUDGETS,
    CONTEXT_SCHEMA,
    PRODUCT_SCHEMA,
    score_product,
    seal_context_product,
    seal_reader_product,
)
from evals.paper.provider import MODEL_ID
from milai.api.app import _embedding_provider
from milai.application.memory_context import MemoryContextCompiler
from milai.application.memory_query import MemoryQueryCompiler
from milai.application.memory_resolve import MemoryResolveService
from milai.application.query_planner import QueryPlanner
from milai.application.retrieval import RetrievalService
from milai.domain.memory_resolve import MemoryResolveBudget, MemoryResolveRequest
from milai.persistence import Database, SessionContext
from milai.persistence.retrieval_repository import RetrievalRepository

from scripts.run_dg16_q6 import _process_identity, _provider_record, _reader_models

S6_RECEIPT = ROOT / "var/dg21/s6/dg21-s6-schema-gate-20260828-006/receipt.json"
S1_RECEIPT = ROOT / "var/dg21/s1/dg21-s1-policy-synthetic-20260828-004/receipt.json"
DG20_PRODUCT = (
    ROOT / "var/dg20/s5/dg20-s5-matched-q6-20260828-002/sealed-product-trace.json"
)
DG21_READER_REUSE_PRODUCTS = (
    ROOT / "var/dg21/s7/dg21-s7-matched-20260828-003/sealed-product-trace.json",
)
OUTPUT_ROOT = ROOT / "var/dg21/s7"
BASELINE_SOURCE_ARM = "B_FRESH_STATE_DETERMINISTIC_CAPABILITY_POLICY"
SEED_RUN_ID = "dg20-s5-matched-q6-20260828-002"
CANDIDATE_CAP = 8
DEADLINE_MS = 2_000
READER_PROGRESS_SCHEMA = "milai.dg21.s7-reader-progress.v0.1"
_SOURCE_REF = re.compile(r"^[^:]+:s\d+:([^:]+):t\d+$")


class DG21S7RunError(RuntimeError):
    pass


def run(
    *, run_id: str, output: Path, env_file: Path, reader_url: str
) -> dict[str, Any]:
    if output.exists():
        raise DG21S7RunError("output exists; use a fresh S7 run ID")
    s6 = _load(S6_RECEIPT)
    s1 = _load(S1_RECEIPT)
    baseline_product = _load(DG20_PRODUCT)
    sealed_reader_products = [
        (path, _load(path)) for path in DG21_READER_REUSE_PRODUCTS
    ]
    reader_progress_paths = tuple(
        sorted(OUTPUT_ROOT.glob("*/reader-progress-trace.json"))
    )
    reader_progress_products = [(path, _load(path)) for path in reader_progress_paths]
    reader_reuse_products = sealed_reader_products + reader_progress_products
    prior_reader_index = _sealed_reader_reuse_index(reader_reuse_products)
    if s6.get("status") != "NOT_ENTERED_SCHEMA_AUTH_REQUIRED":
        raise DG21S7RunError("authoritative S6 typed non-entry is required")
    if s1.get("status") != "PASS_POLICY_SYNTHETIC_MATRIX":
        raise DG21S7RunError("authoritative frozen S1 policy is required")
    output.mkdir(parents=True)
    started = time.perf_counter()
    cpu_started = time.process_time()
    plan = {
        "schema": "milai.dg21.s7-resource-plan.v0.1",
        "run_id": run_id,
        "entry_s6_receipt": _identity(S6_RECEIPT),
        "frozen_policy_receipt": _identity(S1_RECEIPT),
        "dg20_baseline_product": _identity(DG20_PRODUCT),
        "sealed_reader_reuse_products": [
            _identity(path) for path in DG21_READER_REUSE_PRODUCTS
        ],
        "reader_progress_reuse_products": [
            _identity(path) for path in reader_progress_paths
        ],
        "arms": list(ARMS),
        "token_budgets": list(BUDGETS),
        "same_opened_snapshot": True,
        "product_context_sealed_before_reader": True,
        "reader_seed_identity": SEED_RUN_ID,
        "reader_call_ceiling": 60,
        "logical_product_query_count": 60,
        "additional_acquisition_call_ceiling_per_budget": 8,
        "repository_probe_ceiling": 600,
        "rows_scanned_ceiling": 100_000,
        "wall_seconds_ceiling": 7_200,
        "cpu_seconds_ceiling": 7_200,
        "automatic_retries": 0,
        "provider_controller_calls": 0,
        "formal_holdout_consumed": False,
        "policy_tuning_after_s4": False,
        "latency_repeats": "DEFERRED_UNTIL_CORRECTNESS_SEAL",
    }
    plan_path = output / "plan.json"
    _atomic_json(plan_path, plan)

    cases, selection = load_public_dev_cases()
    frozen_context = {
        (row["case_id"], row["token_budget"]): row
        for row in baseline_product["records"]
        if row["arm"] == BASELINE_SOURCE_ARM
    }
    matched_baseline, pairing = _matched_causal_reader_records(
        baseline_product["records"]
    )
    frozen_reader = {
        (row["case_id"], row["token_budget"]): row
        for row in matched_baseline
        if row["arm"] == BASELINE_SOURCE_ARM
    }
    if len(frozen_context) != 20 or len(frozen_reader) != 20:
        raise DG21S7RunError("DG20 baseline denominator drifted")
    session = LocalDG15RuntimeSession(
        output_root=output / "runtime",
        env_file=env_file,
        mcp_concurrency=4,
        projection_batch_size=64,
        inherit_source_embedding_runtime=True,
        barrier_timeout_ms=30_000,
    )
    database: Database | None = None
    deferred: list[tuple[str, Any]] = []
    lifecycle: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    runtime_start: dict[str, Any] = {}
    runtime_close: dict[str, Any] = {"status": "NOT_STARTED"}
    try:
        runtime_start = dict(session.start(run_id))
        settings = session._settings
        urls = session._database_urls
        if settings is None or urls is None:
            raise DG21S7RunError("isolated Runtime settings unavailable")
        database = Database(settings, dsn=urls["api"], expected_role="milai_api")
        repository = RetrievalRepository(database)
        context = SessionContext(settings.tenant_id, settings.local_actor_id)
        embedding = _embedding_provider(settings)
        compiler = MemoryContextCompiler(repository)
        resolvers = {
            ARM_B: MemoryResolveService(
                RetrievalService(
                    repository,
                    embedding=embedding,
                    planner=QueryPlanner(
                        MemoryQueryCompiler(preference_current_intent_enabled=False)
                    ),
                    deterministic_recovery_enabled=True,
                    type_directed_semantics_enabled=True,
                    query_time_event_enabled=False,
                ),
                context_compiler=compiler,
            ),
            ARM_C: MemoryResolveService(
                RetrievalService(
                    repository,
                    embedding=embedding,
                    deterministic_recovery_enabled=True,
                    type_directed_acquisition_enabled=True,
                    query_time_event_enabled=False,
                ),
                context_compiler=compiler,
            ),
            ARM_D: MemoryResolveService(
                RetrievalService(
                    repository,
                    embedding=embedding,
                    deterministic_recovery_enabled=True,
                    type_directed_acquisition_enabled=True,
                    query_time_event_enabled=True,
                ),
                context_compiler=compiler,
            ),
        }
        for ordinal, case in enumerate(cases, start=1):
            adapter = session.adapter_for_case(
                case, lambda text: max(1, (len(text.encode("utf-8")) + 2) // 3)
            )
            deferred.append((case.case_id, adapter))
            namespace = adapter.reset(run_id, case.case_id)
            adapter.ingest_many(case.history_events)
            readiness = dict(adapter.finalize())
            if readiness.get("status") != "READY":
                raise DG21S7RunError(f"case {case.case_id} projection not READY")
            snapshot = _canonical_sha256(
                [event.canonical() for event in case.history_events]
            )
            for budget in BUDGETS:
                base = dict(frozen_context[(case.case_id, budget)])
                if base["source_snapshot_digest"] != snapshot:
                    raise DG21S7RunError("baseline/current source snapshot drifted")
                base.pop("answer", None)
                base.pop("provider", None)
                base["arm"] = ARM_A
                base["method_id"] = ARM_A
                base["reader_source"] = "PENDING_BASELINE_REUSE"
                records.append(base)
                for arm in (ARM_B, ARM_C, ARM_D):
                    records.append(
                        _run_context_cell(
                            resolver=resolvers[arm],
                            arm=arm,
                            run_id=run_id,
                            request_id=f"{run_id}-{ordinal:02d}-{budget}-{arm[0].lower()}",
                            case=case,
                            budget=budget,
                            scope=dict(namespace.scope),
                            session_context=context,
                            source_snapshot_digest=snapshot,
                        )
                    )
            lifecycle.append(
                {
                    "case_id": case.case_id,
                    "readiness_status": readiness["status"],
                    "cleanup_status": "DEFERRED",
                }
            )
            print(
                json.dumps(
                    {
                        "stage": "dg21-s7-context",
                        "case": ordinal,
                        "case_id": case.case_id,
                        "status": "SUCCEEDED",
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    finally:
        for case_id, adapter in deferred:
            try:
                cleanup = dict(adapter.cleanup())
            except (
                DG14Error,
                OSError,
                subprocess.SubprocessError,
                TimeoutError,
            ) as exc:
                cleanup = {
                    "status": "EMERGENCY_CLEANUP_FAILED",
                    "error_type": type(exc).__name__,
                }
            row = next((item for item in lifecycle if item["case_id"] == case_id), None)
            if row is not None:
                row["cleanup_status"] = cleanup.get("status")
        if database is not None:
            database.close()
        runtime_close = dict(session.close())
    context_product = {
        "schema": CONTEXT_SCHEMA,
        "status": "CONTEXTS_COMPLETE_UNREAD",
        "run_id": run_id,
        "labels_loaded": False,
        "formal_holdout_consumed": False,
        "candidate_default": False,
        "selection": selection,
        "records": records,
        "runtime": {"start": runtime_start, "close": runtime_close},
        "lifecycle": lifecycle,
    }
    context_path = output / "sealed-context-trace.json"
    seal_context_product(context_product, context_path)

    provider = MatchedVllmProvider(reader_url)
    reader_calls = 0
    reuse_count = 0
    dg20_reuse_count = 0
    dg21_reuse_count = 0
    fresh_reader_records: list[dict[str, Any]] = []
    reader_progress_path = output / "reader-progress-trace.json"
    completed: list[dict[str, Any]] = []
    for row in records:
        record = dict(row)
        source = frozen_reader[(row["case_id"], row["token_budget"])]
        if row["arm"] == ARM_A or row["context_sha256"] == source["context_sha256"]:
            record["answer"] = source["answer"]
            record["provider"] = source["provider"]
            record["reader_source"] = "DG20_EXACT_CONTEXT_AND_SEED_REUSE"
            reuse_count += 1
            dg20_reuse_count += 1
        elif prior := prior_reader_index.get(
            (
                row["case_id"],
                row["token_budget"],
                row["arm"],
                row["context_sha256"],
            )
        ):
            if prior["context"] != row["context"]:
                raise DG21S7RunError("Reader reuse digest collision")
            record["answer"] = prior["answer"]
            record["provider"] = prior["provider"]
            record["reader_source"] = (
                "DG21_SEALED_EXACT_CONTEXT_AND_READER_IDENTITY_REUSE"
            )
            reuse_count += 1
            dg21_reuse_count += 1
        else:
            # Count the attempted external call before dispatch so a provider-side
            # parse/transport failure cannot disappear from the resource record.
            reader_calls += 1
            try:
                answer = provider.answer(
                    run_id=SEED_RUN_ID,
                    case_id=row["case_id"],
                    method_id=row["arm"],
                    question=next(
                        case.question
                        for case in cases
                        if case.case_id == row["case_id"]
                    ),
                    question_as_of=str(
                        next(
                            case.question_at
                            for case in cases
                            if case.case_id == row["case_id"]
                        )
                    ),
                    memory_context=row["context"],
                    token_budget=row["token_budget"],
                )
            except Exception as exc:
                _atomic_json(
                    output / "reader-failure.json",
                    _reader_failure_record(
                        run_id=run_id,
                        row=row,
                        reader_attempt_ordinal=reader_calls,
                        context_path=context_path,
                        exc=exc,
                    ),
                )
                raise
            if answer.context != row["context"] or answer.context_truncated:
                raise DG21S7RunError("Reader modified a sealed Runtime context")
            record["answer"] = answer.answer
            record["provider"] = _provider_record(answer)
            record["reader_source"] = "FROZEN_READER_AFTER_CONTEXT_SEAL"
            fresh_reader_records.append(record)
            _atomic_json(
                reader_progress_path,
                _reader_progress_product(
                    run_id=run_id,
                    context_path=context_path,
                    records=fresh_reader_records,
                ),
            )
        completed.append(record)
    if reader_calls > 60:
        raise DG21S7RunError("Reader resource plan exceeded")
    product = {
        **{key: value for key, value in context_product.items() if key != "schema"},
        "schema": PRODUCT_SCHEMA,
        "status": "PRODUCT_AND_READER_COMPLETE_UNSCORED",
        "records": completed,
        "reader_calls": reader_calls,
        "reader_reuses": reuse_count,
        "dg20_reader_reuses": dg20_reuse_count,
        "dg21_sealed_reader_reuses": dg21_reuse_count,
        "dg20_matched_reader_pairing": pairing,
        "reader_model_id": "Qwen3.6-35B-A3B-FP8",
        "reader_identity": {
            "url": reader_url,
            "models": _reader_models(reader_url),
            "process": _process_identity(7860),
        },
        "provider_contract_sha256": full_provider_contract_sha256(),
    }
    product_path = output / "sealed-product-trace.json"
    seal_reader_product(product, product_path)
    score = score_product(product_path)
    score_path = output / "score.json"
    _atomic_json(score_path, score)
    probe_calls = sum(_executed_probes(row) for row in completed if row["arm"] != ARM_A)
    rows_scanned = sum(_raw_rows(row) for row in completed if row["arm"] != ARM_A)
    resource_actual = {
        "logical_product_queries": 60,
        "reader_calls": reader_calls,
        "reader_reuses": reuse_count,
        "dg20_reader_reuses": dg20_reuse_count,
        "dg21_sealed_reader_reuses": dg21_reuse_count,
        "repository_probe_calls": probe_calls,
        "rows_scanned": rows_scanned,
        "wall_seconds": round(time.perf_counter() - started, 6),
        "cpu_seconds": round(time.process_time() - cpu_started, 6),
    }
    resource_checks = {
        "reader_within_plan": reader_calls <= 60,
        "repository_probes_within_plan": probe_calls <= 600,
        "rows_scanned_within_plan": rows_scanned <= 100_000,
        "wall_within_plan": resource_actual["wall_seconds"] <= 7_200,
        "cpu_within_plan": resource_actual["cpu_seconds"] <= 7_200,
    }
    receipt = {
        "schema": "milai.dg21.s7-matched-receipt.v0.1",
        "status": score["status"],
        "run_id": run_id,
        "hard_gate": score["hard_gate"],
        "resource_plan_gate": {
            "passed": all(resource_checks.values()),
            "checks": resource_checks,
        },
        "resource_actual": resource_actual,
        "formal_holdout_consumed": False,
        "labels_loaded_only_after_product_seal": True,
        "policy_tuned_during_s7": False,
        "plan": _identity(plan_path),
        "sealed_context_trace": _identity(context_path),
        "sealed_product_trace": _identity(product_path),
        "score": _identity(score_path),
        "reader_progress_trace": (
            _identity(reader_progress_path) if reader_progress_path.exists() else None
        ),
        "entry_s6_receipt": _identity(S6_RECEIPT),
        "frozen_policy_receipt": _identity(S1_RECEIPT),
    }
    receipt_path = output / "receipt.json"
    _atomic_json(receipt_path, receipt)
    return receipt


def _run_context_cell(
    *,
    resolver: MemoryResolveService,
    arm: str,
    run_id: str,
    request_id: str,
    case: Any,
    budget: int,
    scope: dict[str, Any],
    session_context: SessionContext,
    source_snapshot_digest: str,
) -> dict[str, Any]:
    reference = datetime.fromisoformat(
        normalize_lme_timestamp(str(case.question_at)).replace("Z", "+00:00")
    )
    request = MemoryResolveRequest(
        query=str(case.question),
        requested_scope=scope,
        required_authority="INFORMATIONAL",
        required_freshness="CURRENT",
        consistency_mode="CANONICAL_REQUIRED",
        reference_time=reference,
        budget=MemoryResolveBudget(
            max_results=8,
            max_candidates=8,
            max_context_tokens=budget,
            max_latency_ms=2_000,
        ),
    )
    started = time.perf_counter()
    execution = resolver.resolve(session_context, request, request_id)
    query_ms = (time.perf_counter() - started) * 1_000
    body = execution.body
    memory = _object(body.get("memory_context"), "MemoryContext")
    context = memory.get("text")
    if execution.status_code != 200 or not isinstance(context, str) or not context:
        raise DG21S7RunError("Runtime context cell failed")
    items = [dict(item) for item in body.get("items", []) if isinstance(item, dict)]
    refs = _source_refs(items)
    trace = _object(body.get("search_trace"), "search trace")
    recovery = trace.get("deterministic_recovery")
    if not isinstance(recovery, dict):
        recovery = {
            "enabled": False,
            "attempted": False,
            "decision": None,
            "extra_pass_count": 0,
            "provider_calls": 0,
            "automatic_retries": 0,
            "canonical_mutation": False,
        }
    return {
        "case_id": str(case.case_id),
        "category": str(case.category),
        "arm": arm,
        "method_id": arm,
        "token_budget": budget,
        "request_id": request_id,
        "status": body.get("status"),
        "query_latency_ms": round(query_ms, 6),
        "source_snapshot_digest": source_snapshot_digest,
        "context": context,
        "context_sha256": hashlib.sha256(context.encode()).hexdigest(),
        "context_tokens": int(memory.get("estimated_tokens", 0)),
        "semantic_context_digest": memory.get("semantic_context_digest"),
        "reader_context_digest": memory.get("reader_context_digest"),
        "selected_source_refs": [
            compact_lme_source_ref(str(v))
            for v in memory.get("selected_source_turn_refs", [])
            if isinstance(v, str)
        ],
        "all_source_refs": refs,
        "retrieval_trace": [
            {"rank": rank, "source_id": ref, "session_id": _session_id(ref)}
            for rank, ref in enumerate(refs, 1)
        ],
        "evidence_items": items,
        "derived_result": body.get("derived_result"),
        "sufficiency_decision": body.get("sufficiency_decision"),
        "search_trace": trace,
        "memory_query_ir": body.get("memory_query_ir"),
        "recovery": recovery,
        "usage": {
            "retrieval_logical_calls": 1,
            "additional_acquisition_calls": _integer(recovery.get("extra_pass_count")),
            "residual_provider_calls": _integer(recovery.get("provider_calls")),
            "automatic_retries": _integer(recovery.get("automatic_retries")),
            "controller_tokens": 0,
        },
        "reader_source": "PENDING_AFTER_CONTEXT_SEAL",
    }


def _source_refs(items: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for item in items:
        source = item.get("source_ref")
        if isinstance(source, str) and compact_lme_source_ref(source) not in refs:
            refs.append(compact_lme_source_ref(source))
    return refs


def _session_id(ref: str) -> str | None:
    match = _SOURCE_REF.match(ref)
    return match.group(1) if match else None


def _executed_probes(row: dict[str, Any]) -> int:
    return sum(
        1
        for item in row["search_trace"].get("acquisition_probe_dispositions", [])
        if isinstance(item, dict) and item.get("status") == "EXECUTED"
    )


def _raw_rows(row: dict[str, Any]) -> int:
    return sum(
        int(item.get("raw_candidate_count", 0))
        for item in row["search_trace"].get("acquisition_probe_dispositions", [])
        if isinstance(item, dict)
    )


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    return value


def _sealed_reader_reuse_index(
    products: list[tuple[Path, dict[str, Any]]],
) -> dict[tuple[str, int, str, str], dict[str, Any]]:
    """Index only identity-complete Reader results from prior sealed products.

    Reuse is content addressed and independent of case-specific expected answers:
    the public case/budget, exact context bytes, frozen model/provider contract,
    and matched seed must all agree.  Conflicting sealed answers fail closed.
    """

    expected_contract = full_provider_contract_sha256()
    index: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for path, product in products:
        schema = product.get("schema")
        if (
            schema not in {PRODUCT_SCHEMA, READER_PROGRESS_SCHEMA}
            or product.get("labels_loaded") is not False
            or product.get("formal_holdout_consumed") is not False
            or product.get("reader_model_id") != MODEL_ID
            or product.get("provider_contract_sha256") != expected_contract
        ):
            raise DG21S7RunError(f"Reader reuse product identity is invalid: {path}")
        records = product.get("records")
        if not isinstance(records, list):
            raise DG21S7RunError(f"Reader reuse records are invalid: {path}")
        if schema == READER_PROGRESS_SCHEMA and (
            product.get("status") != "READER_PROGRESS_UNSCORED"
            or product.get("automatic_retries") != 0
            or product.get("record_count") != len(records)
        ):
            raise DG21S7RunError(f"Reader progress identity is invalid: {path}")
        for raw in records:
            if not isinstance(raw, dict):
                raise DG21S7RunError(f"Reader reuse record is invalid: {path}")
            if raw.get("reader_source") != "FROZEN_READER_AFTER_CONTEXT_SEAL":
                continue
            case_id = raw.get("case_id")
            budget = raw.get("token_budget")
            arm = raw.get("arm")
            context = raw.get("context")
            context_digest = raw.get("context_sha256")
            answer = raw.get("answer")
            provider = raw.get("provider")
            if (
                not isinstance(case_id, str)
                or not isinstance(budget, int)
                or isinstance(budget, bool)
                or not isinstance(arm, str)
                or not isinstance(context, str)
                or not isinstance(context_digest, str)
                or hashlib.sha256(context.encode()).hexdigest() != context_digest
                or not isinstance(answer, str)
                or not isinstance(provider, dict)
                or provider.get("answer") != answer
                or provider.get("context_sha256") != context_digest
                or provider.get("context_truncated") is not False
                or provider.get("finish_reason") != "stop"
                or provider.get("provider_calls") != 1
                or provider.get("seed") != matched_seed(SEED_RUN_ID, case_id, budget)
                or provider.get("logical_request_id")
                != logical_request_id(SEED_RUN_ID, case_id, arm, budget)
            ):
                raise DG21S7RunError(f"Reader reuse record identity is invalid: {path}")
            key = (case_id, budget, arm, context_digest)
            existing = index.get(key)
            if existing is not None and existing["answer"] != answer:
                raise DG21S7RunError("Conflicting sealed Reader reuse records")
            if existing is None:
                index[key] = raw
    return index


def _reader_progress_product(
    *,
    run_id: str,
    context_path: Path,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build an unscored checkpoint of successful post-seal Reader calls."""

    return {
        "schema": READER_PROGRESS_SCHEMA,
        "status": "READER_PROGRESS_UNSCORED",
        "run_id": run_id,
        "labels_loaded": False,
        "formal_holdout_consumed": False,
        "automatic_retries": 0,
        "reader_model_id": MODEL_ID,
        "provider_contract_sha256": full_provider_contract_sha256(),
        "sealed_context_trace": _identity(context_path),
        "record_count": len(records),
        "records": records,
    }


def _reader_failure_record(
    *,
    run_id: str,
    row: dict[str, Any],
    reader_attempt_ordinal: int,
    context_path: Path,
    exc: Exception,
) -> dict[str, Any]:
    """Describe one failed Reader call without persisting question/context/gold text."""

    case_id = str(row["case_id"])
    arm = str(row["arm"])
    budget = int(row["token_budget"])
    return {
        "schema": "milai.dg21.s7-reader-failure.v0.1",
        "run_id": run_id,
        "phase": "READER_AFTER_CONTEXT_SEAL",
        "case_id": case_id,
        "arm": arm,
        "token_budget": budget,
        "reader_attempt_ordinal": reader_attempt_ordinal,
        "context_sha256": row.get("context_sha256"),
        "semantic_context_digest": row.get("semantic_context_digest"),
        "reader_context_digest": row.get("reader_context_digest"),
        "logical_request_id": logical_request_id(SEED_RUN_ID, case_id, arm, budget),
        "seed": matched_seed(SEED_RUN_ID, case_id, budget),
        "reader_model_id": MODEL_ID,
        "provider_contract_sha256": full_provider_contract_sha256(),
        "sealed_context_trace": _identity(context_path),
        "failure_type": type(exc).__name__,
        "reason": str(exc),
        "automatic_retry_attempted": False,
        "question_context_answer_or_labels_persisted": False,
        "formal_holdout_consumed": False,
    }


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return _object(json.loads(path.read_text(encoding="utf-8")), str(path))


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg21-s7-matched-20260828-008")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--reader-url", default="http://127.0.0.1:7860")
    args = parser.parse_args()
    output = OUTPUT_ROOT / args.run_id
    try:
        receipt = run(
            run_id=args.run_id,
            output=output,
            env_file=args.env_file,
            reader_url=args.reader_url,
        )
    except BaseException as exc:
        if output.exists() and not (output / "failure-ledger.json").exists():
            _atomic_json(
                output / "failure-ledger.json",
                {
                    "schema": "milai.dg21.failure-ledger.v0.1",
                    "run_id": args.run_id,
                    "status": "FAILED_PRESERVED_FOR_DIAGNOSIS",
                    "failure_type": type(exc).__name__,
                    "reason": str(exc),
                    "automatic_retry_attempted": False,
                    "formal_holdout_consumed": False,
                },
            )
        raise
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str((output / "receipt.json").relative_to(ROOT)),
                "hostname": platform.node(),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["status"] == "PASS_TYPE_DIRECTED_ACQUISITION_EFFICIENCY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
