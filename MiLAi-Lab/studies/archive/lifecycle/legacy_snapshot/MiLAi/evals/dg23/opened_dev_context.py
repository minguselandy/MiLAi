"""DG-23 S6 product-faithful opened-development Context ladder."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Any

from milai.api.app import _embedding_provider
from milai.application.memory_context import MemoryContextCompiler
from milai.application.memory_resolve import MemoryResolveService
from milai.application.retrieval import RetrievalService
from milai.domain.memory_resolve import MemoryResolveBudget, MemoryResolveRequest
from milai.domain.reader_evidence_plan import ContextBudgetEnvelope
from milai.persistence import Database, SessionContext
from milai.persistence.retrieval_repository import RetrievalRepository

from evals.dg14.benchmark import DEFAULT_ENV_FILE, DEFAULT_TOKENIZER
from evals.dg14.contracts import DG14Error, normalize_lme_timestamp
from evals.dg15.milai_mcp_adapter import compact_lme_source_ref
from evals.dg15.runtime_session import LocalDG15RuntimeSession
from evals.dg16.lme10 import load_public_dev_cases
from evals.dg17.measurement import load_answer_bearing_labels
from evals.dg23.reader_token_accounting import FrozenReaderTokenCounter

DIAGNOSTIC_BUDGETS = (128, 256, 512, 1024, 2048, 4096, 8000)
READER_MODES = (
    "LEGACY_512",
    "LEGACY_2048",
    "REFERENCE_B_REF",
    "ADAPTIVE_RUNTIME",
)
SAFE_ORACLE_REPORT = Path(
    "var/dg22/s1/dg22-s1-accuracy-oracle-20260829-001/channel-reachability-report.json"
)


class DG23OpenedDevContextError(RuntimeError):
    """Typed S6 product, lifecycle, or invariant failure."""


def build_opened_dev_context_product(
    root: Path,
    *,
    run_id: str,
    output: Path,
    env_file: Path = DEFAULT_ENV_FILE,
) -> dict[str, Any]:
    """Execute one acquisition/decision/plan per case, then exact local renders."""

    cases, selection = load_public_dev_cases()
    reader_tokens = FrozenReaderTokenCounter()
    tokenizer_sha = reader_tokens.tokenizer_sha256
    max_case_events = max(len(case.history_events) for case in cases)
    readiness_deadline_ms = min(120_000, max(30_000, max_case_events * 125))

    session = LocalDG15RuntimeSession(
        output_root=output / "runtime",
        env_file=env_file,
        mcp_concurrency=4,
        projection_batch_size=64,
        inherit_source_embedding_runtime=True,
        barrier_timeout_ms=readiness_deadline_ms,
    )
    database: Database | None = None
    compilers: dict[str, MemoryContextCompiler] = {}
    runtime_start: dict[str, Any] = {}
    runtime_close: dict[str, Any] = {"status": "NOT_STARTED"}
    lifecycle: list[dict[str, Any]] = []
    case_states: list[dict[str, Any]] = []
    diagnostic_records: list[dict[str, Any]] = []
    started = time.perf_counter()
    deferred_adapters: list[tuple[str, Any]] = []
    emergency_cleanup_failure: dict[str, str] | None = None
    try:
        runtime_start = dict(session.start(run_id))
        settings = session._settings
        urls = session._database_urls
        if settings is None or urls is None:
            raise DG23OpenedDevContextError("isolated Runtime settings unavailable")
        database = Database(settings, dsn=urls["api"], expected_role="milai_api")
        repository = RetrievalRepository(database)
        retrieval = RetrievalService(
            repository,
            embedding=_embedding_provider(settings),
            lexical_enrichment_enabled=True,
            evidence_dense_enabled=True,
            deterministic_recovery_enabled=True,
            type_directed_acquisition_enabled=True,
            query_time_event_enabled=True,
            budget_stable_context_enabled=True,
        )
        principal = SessionContext(settings.tenant_id, settings.local_actor_id)
        for ordinal, case in enumerate(cases, start=1):
            case_id = str(case.case_id)
            compiler = MemoryContextCompiler(
                repository,
                budget_stable_enabled=True,
                exact_token_counter=reader_tokens.bind(
                    question=str(case.question),
                    question_as_of=str(case.question_at),
                ),
                exact_tokenizer_identity=tokenizer_sha,
            )
            compilers[case_id] = compiler
            resolver = MemoryResolveService(
                retrieval,
                context_compiler=compiler,
            )
            adapter = session.adapter_for_case(
                case,
                lambda text: max(1, (len(text.encode("utf-8")) + 2) // 3),
            )
            namespace = adapter.reset(run_id, case.case_id)
            deferred_adapters.append((str(case.case_id), adapter))
            lifecycle.append(
                {
                    "case_id": str(case.case_id),
                    "projection_readiness": "PENDING",
                    "cleanup_status": "DEFERRED",
                    "cleanup_accepted": False,
                }
            )
            adapter.ingest_many(case.history_events)
            readiness = dict(adapter.finalize())
            if readiness.get("status") != "READY":
                raise DG23OpenedDevContextError(f"case {case.case_id} projection was not READY")
            lifecycle[-1]["projection_readiness"] = readiness.get("status")
            source_snapshot_digest = _digest([event.canonical() for event in case.history_events])
            reference = datetime.fromisoformat(
                normalize_lme_timestamp(str(case.question_at)).replace("Z", "+00:00")
            )
            source_snapshot_as_of = max(
                reference,
                *(
                    datetime.fromisoformat(event.observed_at.replace("Z", "+00:00"))
                    for event in case.history_events
                ),
            )
            request = MemoryResolveRequest(
                query=str(case.question),
                requested_scope=dict(namespace.scope),
                required_authority="INFORMATIONAL",
                required_freshness="CURRENT",
                consistency_mode="CANONICAL_REQUIRED",
                reference_time=reference,
                budget=MemoryResolveBudget(
                    max_results=8,
                    max_candidates=8,
                    max_context_tokens=8000,
                    max_latency_ms=2_000,
                ),
            )
            query_started = time.perf_counter()
            execution = resolver.resolve(
                principal,
                request,
                f"{run_id}-{ordinal:02d}-official-decision",
                source_snapshot_as_of=source_snapshot_as_of,
            )
            query_latency_ms = (time.perf_counter() - query_started) * 1000
            if (
                execution.status_code != 200
                or execution.decision_snapshot is None
                or execution.context_plan is None
            ):
                raise DG23OpenedDevContextError(
                    f"case {case.case_id} did not expose the internal candidate plan"
                )
            body = execution.body
            plan = execution.context_plan
            decision = execution.decision_snapshot
            usage = _case_usage(body, decision.accepted_evidence_ids)
            all_candidate_refs = _plan_source_refs(plan)
            accepted_binding_refs = list(
                dict.fromkeys(
                    compact_lme_source_ref(span.source_turn_ref)
                    for span in decision.accepted_binding_spans
                )
            )
            case_records = [
                _render_record(
                    compiler=compiler,
                    planned=plan,
                    budget=budget,
                    tokenizer_sha=tokenizer_sha,
                    case_id=case_id,
                    category=str(case.category),
                    source_snapshot_digest=source_snapshot_digest,
                    all_candidate_refs=all_candidate_refs,
                    accepted_binding_refs=accepted_binding_refs,
                    usage=usage,
                    query_latency_ms=query_latency_ms,
                )
                for budget in DIAGNOSTIC_BUDGETS
            ]
            diagnostic_records.extend(case_records)
            full = case_records[-1]
            b_safe = int(full["protected_closure_tokens"])
            if b_safe > 8000:
                raise DG23OpenedDevContextError(
                    f"CONTEXT_BUDGET_INFEASIBLE_REQUIRED_UNITS: case {case.case_id} B_safe={b_safe}"
                )
            sufficiency = body.get("sufficiency_decision")
            sufficiency_values = sufficiency if isinstance(sufficiency, dict) else {}
            sufficiency_status = str(sufficiency_values.get("status", "PARTIAL"))
            b_ready = b_safe if sufficiency_status == "COMPLETE" else None
            activation = full["conditional_activation_thresholds"]
            saturation_budget = max([b_safe, *(int(value) for value in activation.values())])
            case_states.append(
                {
                    "case_id": case_id,
                    "category": str(case.category),
                    "question": str(case.question),
                    "question_as_of": str(case.question_at),
                    "source_snapshot_as_of": source_snapshot_as_of.isoformat(),
                    "source_snapshot_digest": source_snapshot_digest,
                    "decision_snapshot_digest": decision.snapshot_digest,
                    "decision_layer_digests": full["decision_layer_digests"],
                    "reader_evidence_plan_digest": plan.reader_evidence_plan.plan_digest,
                    "b_safe": b_safe,
                    "b_ready": b_ready,
                    "b_present": b_ready if b_ready is not None else b_safe,
                    "saturation_budget": saturation_budget,
                    "sufficiency_status": sufficiency_status,
                    "usage": usage,
                    "recovery_diagnostic": _recovery_diagnostic(body),
                    "official_acquisition_executions": 1,
                    "official_decision_executions": 1,
                    "context_plan_compilations": 1,
                    "initial_product_context_digest": body["memory_context"][
                        "reader_context_digest"
                    ],
                    "initial_product_context": body["memory_context"]["text"],
                    "plan": plan,
                }
            )
    finally:
        emergency_cleanup_failure = _cleanup_deferred_adapters(
            deferred_adapters,
            lifecycle,
        )
        if database is not None:
            database.close()
        runtime_close = dict(session.close())

    if len(compilers) != 10 or len(case_states) != 10:
        raise DG23OpenedDevContextError("opened-dev denominator did not complete")
    b_ref = max(int(state["b_present"]) for state in case_states)
    reader_mode_records: list[dict[str, Any]] = []
    for state in case_states:
        for mode, budget in (
            ("LEGACY_512", 512),
            ("LEGACY_2048", 2048),
            ("REFERENCE_B_REF", b_ref),
            ("ADAPTIVE_RUNTIME", int(state["b_present"])),
        ):
            record = _render_record(
                compiler=compilers[str(state["case_id"])],
                planned=state["plan"],
                budget=budget,
                tokenizer_sha=tokenizer_sha,
                case_id=state["case_id"],
                category=state["category"],
                source_snapshot_digest=state["source_snapshot_digest"],
                all_candidate_refs=next(
                    row["all_candidate_source_refs"]
                    for row in diagnostic_records
                    if row["case_id"] == state["case_id"]
                ),
                accepted_binding_refs=next(
                    row["accepted_binding_source_refs"]
                    for row in diagnostic_records
                    if row["case_id"] == state["case_id"]
                ),
                usage=state["usage"],
                query_latency_ms=next(
                    float(row["query_latency_ms"])
                    for row in diagnostic_records
                    if row["case_id"] == state["case_id"]
                ),
            )
            record["mode"] = mode
            record["question"] = state["question"]
            record["question_as_of"] = state["question_as_of"]
            reader_mode_records.append(record)
    serializable_states = [
        {key: value for key, value in state.items() if key != "plan"} for state in case_states
    ]
    product = {
        "schema": "milai.dg23.s6-opened-dev-context-product.v0.1",
        "status": "SEALED_CONTEXT_PRODUCT_PENDING_SOURCE_SCORER",
        "run_id": run_id,
        "classification": ("PUBLIC_DEIDENTIFIED_OPENED_DEVELOPMENT_10 / EVALUATION_PLANE"),
        "case_order": [state["case_id"] for state in serializable_states],
        "selection": selection,
        "diagnostic_budgets": list(DIAGNOSTIC_BUDGETS),
        "reader_modes": list(READER_MODES),
        "b_ref": b_ref,
        "case_summaries": serializable_states,
        "diagnostic_records": diagnostic_records,
        "reader_mode_records": reader_mode_records,
        "tokenizer": {
            "path_or_id": str(DEFAULT_TOKENIZER.resolve()),
            "sha256": tokenizer_sha,
            "chat_template_path_or_id": str(reader_tokens.chat_template_path),
            "chat_template_sha256": reader_tokens.chat_template_sha256,
            "accounting_identity": reader_tokens.accounting_identity,
            "accounting_method": (
                "FROZEN_CHAT_TEMPLATE_WITH_MEMORY_MINUS_NO_MEMORY_PROMPT_TOKENS"
            ),
        },
        "runtime": {"start": runtime_start, "close": runtime_close},
        "projection_readiness_policy": {
            "identity": "workload-derived-bounded-wait-slices-v0.1",
            "max_case_events": max_case_events,
            "milliseconds_per_event": 125,
            "total_deadline_ms": readiness_deadline_ms,
            "public_wait_slice_ceiling_ms": 30000,
            "data_resubmissions": 0,
            "worker_restarts": 0,
        },
        "lifecycle": lifecycle,
        "emergency_cleanup_failure": emergency_cleanup_failure,
        "execution_counts": {
            "official_acquisition_executions": len(case_states),
            "official_decision_executions": len(case_states),
            "context_plan_compilations": len(case_states),
            "diagnostic_local_renders": len(diagnostic_records),
            "reader_mode_local_renders": len(reader_mode_records),
            "reader_calls": 0,
            "provider_calls": 0,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "labels_loaded": False,
        "answer_labels_loaded": False,
        "formal_holdout_consumed": False,
        "candidate_default": False,
        "candidate_feature_enabled_for_run": True,
        "runtime_case_id_or_gold_routing": False,
        "canonical_mutation": False,
    }
    product["structural_gate"] = structural_gate(product)
    return product


def structural_gate(product: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate label-free decision, Context, and product-path invariants."""

    records = [dict(row) for row in product.get("diagnostic_records", [])]
    summaries = [dict(row) for row in product.get("case_summaries", [])]
    by_case = {
        str(summary["case_id"]): [row for row in records if row["case_id"] == summary["case_id"]]
        for summary in summaries
    }
    nested_violations: list[str] = []
    order_violations: list[str] = []
    saturation_violations: list[str] = []
    for case_id, values in by_case.items():
        ready = [row for row in values if row["readiness"] == "READY"]
        for low, high in pairwise(ready):
            low_ids = tuple(low["selected_unit_ids"])
            high_ids = tuple(high["selected_unit_ids"])
            if not set(low_ids).issubset(high_ids):
                nested_violations.append(case_id)
            if [value for value in high_ids if value in set(low_ids)] != list(low_ids):
                order_violations.append(case_id)
        saturated = [row for row in ready if row["semantic_saturated"]]
        if len({row["reader_context_digest"] for row in saturated}) > 1:
            saturation_violations.append(case_id)
    decision_fields = (
        "source_snapshot",
        "query_ir",
        "acquisition_plan",
        "candidate_snapshot",
        "gate",
        "binding",
        "requirement_state",
        "sufficiency",
        "operator",
    )
    checks = {
        "ten_case_denominator": len(summaries) == len(by_case) == 10,
        "diagnostic_ladder_exact": product.get("diagnostic_budgets") == list(DIAGNOSTIC_BUDGETS),
        "seventy_diagnostic_cells": len(records) == 70
        and all(len(values) == 7 for values in by_case.values()),
        "one_acquisition_per_case": product.get("execution_counts", {}).get(
            "official_acquisition_executions"
        )
        == 10,
        "one_decision_per_case": product.get("execution_counts", {}).get(
            "official_decision_executions"
        )
        == 10,
        "one_plan_per_case": product.get("execution_counts", {}).get("context_plan_compilations")
        == 10,
        "decision_layer_digests_complete": all(
            set(summary["decision_layer_digests"]) == set(decision_fields) for summary in summaries
        ),
        "decision_drift_zero": all(
            len({row["decision_snapshot_digest"] for row in values}) == 1
            for values in by_case.values()
        ),
        "reader_plan_drift_zero": all(
            len({row["reader_evidence_plan_digest"] for row in values}) == 1
            for values in by_case.values()
        ),
        "nestedness_violations_zero": not nested_violations,
        "order_violations_zero": not order_violations,
        "atomic_truncations_zero": all(row["atomic_unit_truncation_count"] == 0 for row in records),
        "protected_unit_loss_zero": all(
            row["readiness"] != "READY"
            or row["protected_unit_count"] <= len(row["selected_unit_ids"])
            for row in records
        ),
        "conflict_side_loss_zero": all(
            row["readiness"] != "READY" or row["conflict_side_loss_count"] == 0 for row in records
        ),
        "required_evidence_packing_loss_zero": all(
            row["readiness"] != "READY" or row["required_evidence_packing_loss_count"] == 0
            for row in records
        ),
        "saturation_violations_zero": not saturation_violations,
        "token_accounting_mismatch_zero": all(
            row["readiness"] != "READY" or int(row["exact_reader_tokens"]) <= int(row["budget"])
            for row in records
        ),
        "product_path_divergence_zero": all(
            next(
                row["reader_context_digest"]
                for row in records
                if row["case_id"] == summary["case_id"] and row["budget"] == 8000
            )
            == summary["initial_product_context_digest"]
            for summary in summaries
        ),
        "b_ref_within_public_ceiling": 0 < int(product.get("b_ref", 0)) <= 8000,
        "reader_calls_zero": product.get("execution_counts", {}).get("reader_calls") == 0,
        "provider_calls_zero": product.get("execution_counts", {}).get("provider_calls") == 0,
        "labels_absent": product.get("labels_loaded") is False
        and product.get("answer_labels_loaded") is False,
        "formal_holdout_untouched": product.get("formal_holdout_consumed") is False,
        "candidate_default_false": product.get("candidate_default") is False,
        "runtime_case_id_or_gold_routing_zero": product.get("runtime_case_id_or_gold_routing")
        is False,
        "canonical_mutation_zero": product.get("canonical_mutation") is False,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "nestedness_violations": sorted(set(nested_violations)),
        "order_violations": sorted(set(order_violations)),
        "saturation_violations": sorted(set(saturation_violations)),
    }


def seal_opened_dev_context_product(product: Mapping[str, Any], path: Path) -> None:
    """Seal only a complete label-free product; never overwrite."""

    forbidden = {"answers", "atoms", "gold_ir", "scorer_truth"}
    if (
        path.exists()
        or product.get("schema") != "milai.dg23.s6-opened-dev-context-product.v0.1"
        or product.get("labels_loaded") is not False
        or product.get("formal_holdout_consumed") is not False
        or not product.get("structural_gate", {}).get("passed")
        or forbidden.intersection(_recursive_keys(product))
    ):
        raise DG23OpenedDevContextError("S6 label-free product failed seal checks")
    path.write_text(
        json.dumps(product, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def score_opened_dev_context_product(root: Path, path: Path) -> dict[str, Any]:
    """Open required-source labels only after hashing the sealed Context product."""

    sealed_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    product = _object(json.loads(path.read_text(encoding="utf-8")), "product")
    if product.get("labels_loaded") is not False or not product.get("structural_gate", {}).get(
        "passed"
    ):
        raise DG23OpenedDevContextError("S6 scorer requires a sealed label-free PASS")
    _label_envelope, cases, labels = load_answer_bearing_labels()
    if [case.case_id for case in cases] != product["case_order"]:
        raise DG23OpenedDevContextError("S6 scorer denominator drifted")
    required = {
        case_id: [str(atom["source_turn_ref"]) for atom in label["atoms"]]
        for case_id, label in labels.items()
    }
    mode_records = [dict(row) for row in product["reader_mode_records"]]
    scored_records: list[dict[str, Any]] = []
    for row in mode_records:
        required_refs = required[row["case_id"]]
        scored_records.append(_score_mode_record(row, required_refs))
    summaries = {mode: _mode_summary(scored_records, mode) for mode in READER_MODES}
    reference = summaries["REFERENCE_B_REF"]
    legacy_512 = summaries["LEGACY_512"]
    safe_oracle = _object(
        json.loads((root / SAFE_ORACLE_REPORT).read_text(encoding="utf-8")),
        "safe oracle report",
    )
    denominator = int(safe_oracle["metrics"]["safe_oracle_requirement_denominator"])
    reference_rows = [row for row in scored_records if row["mode"] == "REFERENCE_B_REF"]
    found_requirements = {
        (row["case_id"], requirement_id)
        for row in reference_rows
        for requirement_id in row["found_requirement_ids"]
    }
    safe_oracle_recall = min(len(found_requirements), denominator) / denominator
    accepted_total = reference["accepted_binding_count"]
    false_total = reference["false_accepted_binding_count"]
    binding_precision = (accepted_total - false_total) / accepted_total if accepted_total else 1.0
    candidates_hydrated = sum(int(row["usage"]["candidates_hydrated"]) for row in reference_rows)
    useful_candidates = sum(int(row["usage"]["useful_candidate_count"]) for row in reference_rows)
    useful_rate = useful_candidates / candidates_hydrated if candidates_hydrated else 1.0
    regression = next(row for row in reference_rows if row["case_id"] == "gpt4_88806d6e")
    regression_2048 = next(
        row
        for row in scored_records
        if row["case_id"] == "gpt4_88806d6e" and row["mode"] == "LEGACY_2048"
    )
    checks = {
        "structural_gate_passed": product["structural_gate"]["passed"],
        "safe_oracle_normalized_recall_at_least_080": safe_oracle_recall >= 0.80,
        "required_evidence_coverage_reference_at_least_19_of_23": reference["covered_atom_count"]
        >= 19,
        "required_evidence_coverage_512_at_least_18_of_23": legacy_512["covered_atom_count"] >= 18,
        "accepted_binding_precision_100": binding_precision == 1.0,
        "useful_candidate_rate_floor": useful_rate >= 0.34615384615384615,
        "additional_acquisition_calls_at_most_6": sum(
            int(row["usage"]["additional_acquisition_calls"]) for row in reference_rows
        )
        <= 6,
        "candidates_hydrated_at_most_26": candidates_hydrated <= 26,
        "wrong_complete_zero": reference["wrong_complete_count"] == 0
        and legacy_512["wrong_complete_count"] == 0,
        "correct_case_required_source_retention_100": regression["covered_atom_count"]
        == regression["required_atom_count"],
        "historical_regression_2048_context_ready": regression_2048["readiness"] == "READY"
        and regression_2048["covered_atom_count"] == regression_2048["required_atom_count"],
        "labels_loaded_after_product_seal": True,
        "formal_holdout_untouched": product["formal_holdout_consumed"] is False,
    }
    return {
        "schema": "milai.dg23.s6-opened-dev-context-score.v0.1",
        "status": "PASS_DG23_OPENED_DEV_CONTEXT_LADDER"
        if all(checks.values())
        else "FAIL_DG23_OPENED_DEV_CONTEXT_LADDER",
        "sealed_context_product_sha256_before_label_open": sealed_sha,
        "summaries": summaries,
        "metrics": {
            "b_ref": product["b_ref"],
            "b_safe_min": min(row["b_safe"] for row in product["case_summaries"]),
            "b_safe_p50": median(row["b_safe"] for row in product["case_summaries"]),
            "b_safe_max": max(row["b_safe"] for row in product["case_summaries"]),
            "safe_oracle_normalized_recall": safe_oracle_recall,
            "safe_oracle_found_requirement_count": min(len(found_requirements), denominator),
            "safe_oracle_requirement_denominator": denominator,
            "required_evidence_coverage_reference": reference["covered_atom_count"],
            "required_evidence_coverage_512": legacy_512["covered_atom_count"],
            "accepted_binding_precision": binding_precision,
            "useful_candidate_rate": useful_rate,
            "additional_acquisition_calls": sum(
                int(row["usage"]["additional_acquisition_calls"]) for row in reference_rows
            ),
            "candidates_hydrated": candidates_hydrated,
            "wrong_complete": reference["wrong_complete_count"]
            + legacy_512["wrong_complete_count"],
        },
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
        "scored_records": scored_records,
        "first_loss_ledger": _first_loss(scored_records, required),
        "labels_loaded_after_product_seal": True,
        "formal_holdout_consumed": False,
    }


def _render_record(
    *,
    compiler: MemoryContextCompiler,
    planned: Any,
    budget: int,
    tokenizer_sha: str,
    case_id: str,
    category: str,
    source_snapshot_digest: str,
    all_candidate_refs: Sequence[str],
    accepted_binding_refs: Sequence[str],
    usage: Mapping[str, int],
    query_latency_ms: float,
) -> dict[str, Any]:
    compilation = compiler.render(
        planned,
        ContextBudgetEnvelope(
            requested_cap=budget,
            model_context_limit=budget,
            available_memory_tokens=budget,
            reader_tokenizer_identity=tokenizer_sha,
            budget_source="EXACT_READER_ENVELOPE",
        ),
    )
    render = compilation.reader_render
    if render is None:
        raise DG23OpenedDevContextError("candidate render receipt is absent")
    memory = compilation.memory_context
    trace = memory.compile_trace
    selected_ids = set(render.selected_unit_ids)
    conflict_units = [
        unit.unit_id
        for unit in planned.reader_evidence_plan.protected_units
        if unit.kind == "CONFLICT_SIDE"
    ]
    decision = planned.decision_snapshot
    return {
        "case_id": case_id,
        "category": category,
        "budget": budget,
        "readiness": render.readiness,
        "source_snapshot_digest": source_snapshot_digest,
        "decision_snapshot_digest": decision.snapshot_digest,
        "decision_layer_digests": trace["decision_layer_digests"],
        "reader_evidence_plan_digest": planned.reader_evidence_plan.plan_digest,
        "selected_unit_ids": list(render.selected_unit_ids),
        "omitted_unit_reasons": dict(render.omitted_unit_reasons),
        "reader_context_digest": render.reader_context_digest,
        "context": render.text,
        "estimated_tokens": render.estimated_tokens,
        "exact_reader_tokens": render.exact_tokens,
        "reader_tokenizer_path_or_id": str(DEFAULT_TOKENIZER.resolve()),
        "reader_tokenizer_sha256": tokenizer_sha,
        "budget_ceiling": budget,
        "accounting_delta": render.exact_tokens - render.estimated_tokens,
        "protected_closure_tokens": render.protected_closure_tokens,
        "semantic_saturated": render.semantic_saturated,
        "conditional_activation_thresholds": trace["conditional_activation_thresholds"],
        "protected_unit_count": trace["protected_unit_count"],
        "conditional_unit_count": trace["conditional_unit_count"],
        "atomic_unit_truncation_count": trace["atomic_unit_truncation_count"],
        "conflict_side_loss_count": sum(unit_id not in selected_ids for unit_id in conflict_units),
        "required_evidence_packing_loss_count": trace["required_evidence_packing_loss_count"],
        "required_source_turn_packing_loss_count": trace["required_source_turn_packing_loss_count"],
        "selected_evidence_ids": list(memory.selected_evidence_ids),
        "selected_source_refs": [
            compact_lme_source_ref(value) for value in memory.selected_source_turn_refs
        ],
        "all_candidate_source_refs": list(all_candidate_refs),
        "accepted_binding_source_refs": list(accepted_binding_refs),
        "required_requirement_ids": list(decision.required_requirement_ids),
        "unresolved_requirement_ids": list(decision.unresolved_requirement_ids),
        "found_requirement_ids": sorted(
            set(decision.required_requirement_ids).difference(decision.unresolved_requirement_ids)
        ),
        "sufficiency_status": _sufficiency_status(planned.outcome),
        "operator_ready": _operator_ready(planned.outcome),
        "usage": dict(usage),
        "query_latency_ms": round(query_latency_ms, 6),
        "reader_calls": 0,
        "provider_calls": 0,
        "canonical_mutation": trace["canonical_mutation"],
    }


def _cleanup_deferred_adapters(
    deferred: Sequence[tuple[str, Any]],
    lifecycle: list[dict[str, Any]],
) -> dict[str, str] | None:
    """Submit each isolated namespace cleanup once, outside the measurement lane."""

    first_failure: dict[str, str] | None = None
    for case_id, adapter in reversed(deferred):
        row = next(item for item in lifecycle if item["case_id"] == case_id)
        try:
            cleanup = dict(adapter.cleanup())
        except (DG14Error, OSError, subprocess.SubprocessError, TimeoutError) as exc:
            row["cleanup_status"] = "EMERGENCY_CLEANUP_FAILED"
            row["cleanup_accepted"] = False
            if first_failure is None:
                first_failure = {
                    "case_id": case_id,
                    "error_type": type(exc).__name__,
                    "status": "EMERGENCY_CLEANUP_FAILED",
                }
        else:
            row["cleanup_status"] = cleanup.get("status")
            row["cleanup_accepted"] = cleanup.get("cleanup_accepted")
    return first_failure


def _case_usage(body: Mapping[str, Any], accepted_evidence_ids: Sequence[str]) -> dict[str, int]:
    trace = body.get("search_trace")
    values = trace if isinstance(trace, dict) else {}
    recovery = values.get("deterministic_recovery")
    recovery_values = recovery if isinstance(recovery, dict) else {}
    additional = _integer(recovery_values.get("extra_pass_count"))
    accuracy = recovery_values.get("accuracy_acquisition")
    accuracy_values = accuracy if isinstance(accuracy, dict) else {}
    candidate_counts = values.get("candidate_counts")
    candidate_values = candidate_counts if isinstance(candidate_counts, dict) else {}
    hydrated = (
        (
            _integer(accuracy_values.get("candidates_hydrated"))
            if accuracy_values
            else _integer(candidate_values.get("evidence_slot_union"))
        )
        if additional
        else 0
    )
    useful = (
        (
            _integer(accuracy_values.get("useful_candidate_count"))
            if accuracy_values
            else min(hydrated, len(set(accepted_evidence_ids)))
        )
        if additional
        else 0
    )
    return {
        "additional_acquisition_calls": additional,
        "candidates_hydrated": hydrated,
        "useful_candidate_count": useful,
        "provider_controller_calls": _integer(recovery_values.get("provider_calls")),
        "automatic_retries": _integer(recovery_values.get("automatic_retries")),
        "hidden_model_calls": 0,
    }


def _recovery_diagnostic(body: Mapping[str, Any]) -> dict[str, Any]:
    """Retain label-free decision provenance needed for failed-run reflection."""

    trace = body.get("search_trace")
    trace_values = trace if isinstance(trace, dict) else {}
    recovery = trace_values.get("deterministic_recovery")
    values = recovery if isinstance(recovery, dict) else {}
    return {
        key: values.get(key)
        for key in (
            "attempted",
            "initial_requirement_state_digest",
            "initial_requirement_state_epoch",
            "initial_requirement_dispositions",
            "decision",
            "execution_selection",
            "superseded_execution_selection",
            "accuracy_decision",
            "accuracy_acquisition",
            "extra_pass_count",
        )
    }


def _source_refs(raw_items: object) -> list[str]:
    items = raw_items if isinstance(raw_items, list) else []
    return list(
        dict.fromkeys(
            compact_lme_source_ref(str(item["source_ref"]))
            for item in items
            if isinstance(item, dict) and isinstance(item.get("source_ref"), str)
        )
    )


def _plan_source_refs(planned: Any) -> list[str]:
    """Return every source admitted to the immutable ReaderEvidencePlan."""

    units = (
        *planned.reader_evidence_plan.protected_units,
        *planned.reader_evidence_plan.conditional_units,
    )
    return list(
        dict.fromkeys(
            compact_lme_source_ref(source_ref)
            for unit in units
            for source_ref in unit.source_turn_refs
        )
    )


def _sufficiency_status(outcome: Mapping[str, Any]) -> str:
    decision = outcome.get("sufficiency_decision")
    return str(decision.get("status", "PARTIAL")) if isinstance(decision, dict) else "PARTIAL"


def _operator_ready(outcome: Mapping[str, Any]) -> bool:
    derived = outcome.get("derived_result")
    return isinstance(derived, dict) and derived.get("status") in {"COMPLETE", "OK"}


def _mode_summary(records: Sequence[Mapping[str, Any]], mode: str) -> dict[str, int]:
    values = [row for row in records if row["mode"] == mode]
    if len(values) != 10:
        raise DG23OpenedDevContextError(f"mode {mode} denominator drifted")
    return {
        "case_count": len(values),
        "required_atom_count": sum(int(row["required_atom_count"]) for row in values),
        "covered_atom_count": sum(int(row["covered_atom_count"]) for row in values),
        "accepted_binding_count": sum(int(row["accepted_binding_count"]) for row in values),
        "false_accepted_binding_count": sum(
            len(row["false_accepted_binding_refs"]) for row in values
        ),
        "wrong_complete_count": sum(bool(row["wrong_complete"]) for row in values),
        "budget_infeasible_count": sum(row["readiness"] == "BUDGET_INFEASIBLE" for row in values),
    }


def _score_mode_record(
    row: Mapping[str, Any],
    required_refs: Sequence[str],
) -> dict[str, Any]:
    """Project a Reader-mode row without discarding first-loss provenance."""

    selected = set(row["selected_source_refs"])
    candidates = set(row["all_candidate_source_refs"])
    accepted = set(row["accepted_binding_source_refs"])
    covered = [value for value in required_refs if value in selected]
    false_bindings = sorted(accepted.difference(required_refs))
    wrong_complete = row["sufficiency_status"] == "COMPLETE" and len(covered) < len(required_refs)
    return {
        "case_id": row["case_id"],
        "mode": row["mode"],
        "budget": row["budget"],
        "readiness": row["readiness"],
        "required_atom_count": len(required_refs),
        "covered_atom_count": len(covered),
        "covered_atom_refs": covered,
        "all_candidate_source_refs": sorted(candidates),
        "accepted_binding_source_refs": sorted(accepted),
        "false_accepted_binding_refs": false_bindings,
        "accepted_binding_count": len(accepted),
        "required_candidate_count": len(set(required_refs).intersection(candidates)),
        "wrong_complete": wrong_complete,
        "found_requirement_ids": row["found_requirement_ids"],
        "usage": row["usage"],
    }


def _first_loss(
    records: Sequence[Mapping[str, Any]],
    required: Mapping[str, Sequence[str]],
) -> list[dict[str, Any]]:
    rows = [row for row in records if row["mode"] == "REFERENCE_B_REF"]
    ledger = []
    for row in rows:
        candidates = set(row["all_candidate_source_refs"])
        accepted = set(row["accepted_binding_source_refs"])
        selected = set(row["covered_atom_refs"])
        for source_ref in required[row["case_id"]]:
            if source_ref in selected:
                loss = "NONE"
            elif source_ref not in candidates:
                loss = "ACQUISITION"
            elif source_ref not in accepted:
                loss = "BINDING"
            elif row["readiness"] != "READY":
                loss = "PRESENTATION_BUDGET"
            else:
                loss = "READER_PLAN"
            ledger.append(
                {
                    "case_id": row["case_id"],
                    "source_turn_ref": source_ref,
                    "first_loss": loss,
                }
            )
    return ledger


def _recursive_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return {
            *(str(key) for key in value),
            *(key for item in value.values() for key in _recursive_keys(item)),
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return {key for item in value for key in _recursive_keys(item)}
    return set()


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DG23OpenedDevContextError(f"{name} must be an object")
    return value


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


__all__ = [
    "DIAGNOSTIC_BUDGETS",
    "READER_MODES",
    "DG23OpenedDevContextError",
    "build_opened_dev_context_product",
    "score_opened_dev_context_product",
    "seal_opened_dev_context_product",
    "structural_gate",
]
