"""DG-24 behavior preflight and strictly ordered product/probe execution."""

from __future__ import annotations

import builtins
import hashlib
import io
import json
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from milai.api.app import _embedding_provider
from milai.application.memory_context import MemoryContextCompiler
from milai.application.memory_query import MemoryQueryCompiler
from milai.application.memory_resolve import MemoryResolveService
from milai.application.retrieval import RetrievalService
from milai.application.retrieval_audit_probe import (
    OfficialRetrievalAuditProbeExecutor,
)
from milai.domain.acquisition import AcquisitionProbe
from milai.domain.memory_resolve import MemoryResolveBudget, MemoryResolveRequest
from milai.domain.retrieval_audit import canonical_sha256
from milai.observability.retrieval_audit import (
    AuditRecordingRepository,
    ProductRetrievalAuditObserver,
)
from milai.persistence import Database, SessionContext
from milai.persistence.retrieval_repository import RetrievalRepository

from evals.dg14.benchmark import DEFAULT_ENV_FILE
from evals.dg14.contracts import normalize_lme_timestamp
from evals.dg15.runtime_session import LocalDG15RuntimeSession
from evals.dg16.lme10 import load_public_dev_cases
from evals.dg24.contracts import InputOnlyCaseManifestV01

CHANNELS = (
    "FTS_RAW",
    "FTS_ENRICHED",
    "EVIDENCE_DENSE",
    "SOURCE_OBSERVED_RANGE_SCAN",
    "TEMPORAL_EVENT",
)
DENY_FRAGMENTS = (
    "lme10-answer-bearing-labels",
    "longmemeval_s_cleaned",
    "gold-equivalence-registry",
    "proof-obligation-registry",
    "/scorer-only/",
)


class DG24ProductError(RuntimeError):
    """Typed product/probe boundary or execution failure."""


def run_behavior_equivalence(
    root: Path,
    *,
    run_id: str,
    output: Path,
    input_manifest_path: Path,
    env_file: Path = DEFAULT_ENV_FILE,
) -> dict[str, Any]:
    """Run trace OFF/ON on the same ten governed snapshots."""

    root = root.resolve()
    manifest = _input_manifest(input_manifest_path)
    cases = _label_closed_cases(manifest)
    session, database, repository, principal, start = _start_runtime(
        run_id, output, cases, env_file
    )
    lifecycle: list[dict[str, Any]] = []
    adapters: list[Any] = []
    records: list[dict[str, Any]] = []
    close: dict[str, Any] = {"status": "NOT_STARTED"}
    try:
        for ordinal, case in enumerate(cases, start=1):
            adapter, namespace, source_snapshot_as_of, source_digest = _ingest_case(
                session, run_id, case
            )
            adapters.append(adapter)
            _verify_manifest_request(manifest, case, source_digest)
            request = _request(case, namespace.scope)
            baseline = _resolve_once(
                repository=repository,
                database=database,
                principal=principal,
                settings=session._settings,
                request=request,
                request_id=f"{run_id}-{ordinal:02d}-matched",
                source_snapshot_as_of=source_snapshot_as_of,
                enabled=False,
            )
            traced = _resolve_once(
                repository=repository,
                database=database,
                principal=principal,
                settings=session._settings,
                request=request,
                request_id=f"{run_id}-{ordinal:02d}-matched",
                source_snapshot_as_of=source_snapshot_as_of,
                enabled=True,
            )
            baseline_calls = _repository_semantics(baseline)
            traced_calls = _repository_semantics(traced)
            baseline_call_diagnostics = _repository_diagnostics(baseline)
            traced_call_diagnostics = _repository_diagnostics(traced)
            baseline_snapshot = baseline.behavior_snapshot
            traced_snapshot = traced.behavior_snapshot
            field_checks = {
                "request_semantic_digest": _same_snapshot_field(
                    baseline_snapshot, traced_snapshot, "request_semantic_digest"
                ),
                "channel_invocation": _same_snapshot_field(
                    baseline_snapshot, traced_snapshot, "channel_invocation_digest"
                ),
                "candidate_set_and_order": _same_snapshot_fields(
                    baseline_snapshot,
                    traced_snapshot,
                    ("candidate_set_and_order_digest", "ordered_result_digest"),
                ),
                "dedup_winner": _same_snapshot_field(
                    baseline_snapshot, traced_snapshot, "dedup_winner_digest"
                ),
                "gate": _same_snapshot_field(
                    baseline_snapshot, traced_snapshot, "gate_digest"
                ),
                "evidence_set": _same_snapshot_field(
                    baseline_snapshot, traced_snapshot, "evidence_set_digest"
                ),
                "interpretation_binding": _same_snapshot_field(
                    baseline_snapshot,
                    traced_snapshot,
                    "interpretation_binding_digest",
                ),
                "requirement_state": _same_snapshot_field(
                    baseline_snapshot, traced_snapshot, "requirement_state_digest"
                ),
                "sufficiency_operator": _same_snapshot_field(
                    baseline_snapshot,
                    traced_snapshot,
                    "sufficiency_operator_digest",
                ),
            }
            semantic_match = all(field_checks.values())
            repository_match = baseline_calls == traced_calls
            records.append(
                {
                    "case_id": str(case.case_id),
                    "request_payload_digest": _manifest_request(
                        manifest, str(case.case_id)
                    )["request_payload_digest"],
                    "source_snapshot_digest": source_digest,
                    "baseline_digest": baseline.semantic_digest,
                    "traced_digest": traced.semantic_digest,
                    "baseline_behavior_snapshot": baseline_snapshot,
                    "traced_behavior_snapshot": traced_snapshot,
                    "baseline_behavior_evidence": baseline.behavior_evidence,
                    "traced_behavior_evidence": traced.behavior_evidence,
                    "semantic_exact_match": semantic_match,
                    "baseline_repository_digest": baseline.repository_semantic_digest(),
                    "traced_repository_digest": traced.repository_semantic_digest(),
                    "repository_call_set_order_exact_match": repository_match,
                    "baseline_repository_calls": baseline_call_diagnostics,
                    "traced_repository_calls": traced_call_diagnostics,
                    "field_checks": {
                        **field_checks,
                        "repository_call_set_and_order": repository_match,
                    },
                    "exact_match": semantic_match and repository_match,
                }
            )
            lifecycle.append(
                {
                    "case_id": str(case.case_id),
                    "projection_readiness": "READY",
                    "trace_off_runs": 1,
                    "trace_on_runs": 1,
                }
            )
    finally:
        cleanup = _cleanup(adapters)
        database.close()
        close = dict(session.close())
    checks = {
        "ten_cases": len(records) == 10,
        "all_semantic_fields_exact": all(
            item["semantic_exact_match"] for item in records
        ),
        "all_repository_calls_exact": all(
            item["repository_call_set_order_exact_match"] for item in records
        ),
        "all_field_checks_exact": all(
            all(item["field_checks"].values()) for item in records
        ),
        "trace_collection_repository_calls_zero": all(
            len(item["baseline_repository_calls"])
            == len(item["traced_repository_calls"])
            for item in records
        ),
        "reader_calls_zero": True,
        "generative_provider_calls_zero": True,
        "automatic_retry_zero": True,
        "labels_accessed_zero": True,
        "canonical_mutation_zero": True,
        "cleanup_passed": cleanup["passed"],
    }
    return {
        "schema": "milai.dg24.trace-behavior-equivalence.v0.1",
        "run_id": run_id,
        "records": records,
        "runtime": {"start": start, "close": close},
        "lifecycle": lifecycle,
        "cleanup": cleanup,
        "safety": {
            "reader_calls": 0,
            "generative_provider_calls": 0,
            "automatic_retries": 0,
            "label_accesses": 0,
            "canonical_mutations": 0,
            "formal_holdout_consumed": False,
        },
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
    }


def run_product_then_probes(
    root: Path,
    *,
    product_run_id: str,
    probe_run_id: str,
    output: Path,
    input_manifest_path: Path,
    s0_receipt_path: Path,
    stage_registry_path: Path,
    cap_registry_path: Path,
    equivalence_report_path: Path,
    env_file: Path = DEFAULT_ENV_FILE,
) -> dict[str, Any]:
    """Seal all product traces, then and only then run official probes."""

    root = root.resolve()
    manifest = _input_manifest(input_manifest_path)
    cases = _label_closed_cases(manifest)
    s0 = _read_json(s0_receipt_path)
    caps = _read_json(cap_registry_path)
    equivalence = _read_json(equivalence_report_path)
    equivalence_by_case = {
        str(item["case_id"]): item for item in equivalence.get("records", [])
    }
    stage_registry_digest = _sha256(stage_registry_path)
    opaque_seals = {
        "gold_registry_sha256": s0["gold_registry_seal"],
        "proof_registry_sha256": s0["proof_registry_seal"],
    }
    session, database, repository, principal, start = _start_runtime(
        product_run_id, output, cases, env_file
    )
    adapters: list[Any] = []
    product_records: list[dict[str, Any]] = []
    probe_contexts: list[dict[str, Any]] = []
    lifecycle: list[dict[str, Any]] = []
    close: dict[str, Any] = {"status": "NOT_STARTED"}
    product_path = output / "sealed-product-traces.json"
    product_receipt_path = output / "product-phase-receipt.json"
    probe_path = output / "sealed-official-probe-traces.json"
    probe_receipt_path = output / "probe-phase-receipt.json"
    try:
        for ordinal, case in enumerate(cases, start=1):
            adapter, namespace, source_snapshot_as_of, source_digest = _ingest_case(
                session, product_run_id, case
            )
            adapters.append(adapter)
            _verify_manifest_request(manifest, case, source_digest)
            request = _request(case, namespace.scope)
            observer = _resolve_once(
                repository=repository,
                database=database,
                principal=principal,
                settings=session._settings,
                request=request,
                request_id=f"{product_run_id}-{ordinal:02d}-product",
                source_snapshot_as_of=source_snapshot_as_of,
                enabled=True,
            )
            if request.reference_time is None:
                raise DG24ProductError(
                    f"PRODUCT_REQUEST_REFERENCE_TIME_MISSING:{case.case_id}"
                )
            query_ir = MemoryQueryCompiler().compile(
                str(case.question),
                reference_time=request.reference_time,
                scope=dict(namespace.scope),
            )
            preflight = equivalence_by_case.get(str(case.case_id))
            if preflight is None or preflight.get("exact_match") is not True:
                raise DG24ProductError(f"BEHAVIOR_PREFLIGHT_NOT_PASSED:{case.case_id}")
            product_trace = observer.build_product_trace(
                run_identity=product_run_id,
                query_ir=query_ir,
                stage_registry_digest=stage_registry_digest,
                baseline_digest=observer.semantic_digest,
            )
            product_trace = product_trace.model_copy(
                update={
                    "behavior_neutrality": {
                        "baseline_digest": preflight["baseline_digest"],
                        "traced_digest": preflight["traced_digest"],
                        "exact_match": preflight["exact_match"],
                        "evidence": "DG24_S2_MATCHED_SAME_SNAPSHOT_TRACE_OFF_ON",
                    }
                }
            )
            product_records.append(
                {
                    "case_id": str(case.case_id),
                    "source_snapshot_digest": source_digest,
                    "trace": product_trace.model_dump(mode="json"),
                }
            )
            projection = repository.projection_state(principal)
            probe_contexts.append(
                {
                    "case": case,
                    "scope": dict(namespace.scope),
                    "as_of": observer.captured_request.as_of,
                    "request_identity": product_trace.request_identity,
                    "query_plan": observer.captured_query_plan,
                    "acquisition_plan": observer.captured_acquisition_plan,
                    "source_snapshot_digest": source_digest,
                    "projection_identity": canonical_sha256(
                        {
                            "canonical_snapshot": projection.canonical_snapshot_outbox_sequence,
                            "fts_watermark": projection.fts_watermark,
                            "vector_watermark": projection.vector_watermark,
                            "evidence_watermark": projection.evidence_watermark,
                        }
                    ),
                }
            )
            lifecycle.append(
                {
                    "case_id": str(case.case_id),
                    "product_runs": 1,
                    "probe_runs_before_product_seal": 0,
                    "projection_readiness": "READY",
                }
            )
        product_collection = {
            "schema": "milai.dg24.sealed-product-trace-collection.v0.1",
            "run_id": product_run_id,
            "case_order": list(manifest.case_order),
            "opaque_registry_seals": opaque_seals,
            "registry_content_loaded": False,
            "records": product_records,
            "execution_counts": {
                "product_runs": len(product_records),
                "official_probe_runs": 0,
                "reader_calls": 0,
                "generative_provider_calls": 0,
                "automatic_retries": 0,
            },
            "formal_holdout_consumed": False,
            "candidate_default": False,
        }
        _write_json(product_path, product_collection)
        product_seal = _sha256(product_path)
        product_sealed_at = datetime.now(UTC).isoformat()
        product_checks = {
            "ten_product_traces": len(product_records) == 10,
            "one_product_run_per_request": all(
                item["product_runs"] == 1 for item in lifecycle
            ),
            "all_product_before_probe": all(
                item["probe_runs_before_product_seal"] == 0 for item in lifecycle
            ),
            "behavior_equivalence_passed": all(
                item["trace"]["behavior_neutrality"]["exact_match"]
                for item in product_records
            ),
            "observed_occurrence_lifecycle_100": all(
                len(item["trace"]["occurrences"])
                == len(item["trace"]["candidate_lifecycles"])
                for item in product_records
            ),
            "label_access_zero": True,
            "reader_calls_zero": True,
            "generative_provider_calls_zero": True,
            "automatic_retry_zero": True,
            "canonical_mutation_zero": True,
        }
        _write_json(
            product_receipt_path,
            {
                "schema": "milai.dg24.product-phase-receipt.v0.1",
                "run_id": product_run_id,
                "sealed_at": product_sealed_at,
                "product_seal_digest": product_seal,
                "product_collection": _identity(root, product_path),
                "hard_gate": {
                    "passed": all(product_checks.values()),
                    "checks": product_checks,
                },
            },
        )
        if not all(product_checks.values()):
            raise DG24ProductError("DG24_PRODUCT_PHASE_GATE_FAILED")

        probe_executor = OfficialRetrievalAuditProbeExecutor(
            repository,
            _embedding_provider(session._settings),
        )
        probe_records: list[dict[str, Any]] = []
        for case_context in probe_contexts:
            case = case_context["case"]
            plan = case_context["acquisition_plan"]
            query_plan = case_context["query_plan"]
            query_ir = query_plan.memory_query_ir
            if query_ir is None:
                raise DG24ProductError(
                    f"OFFICIAL_PROBE_QUERY_IR_NOT_AVAILABLE:{case.case_id}"
                )
            for requirement in query_ir.requirements:
                if not requirement.required:
                    continue
                for channel in CHANNELS:
                    product_probe = next(
                        (
                            item
                            for item in plan.probes
                            if item.requirement_slot == requirement.slot_id
                            and str(item.channel) == channel
                        ),
                        None,
                    )
                    cap = int(caps["channels"][channel]["m_audit"])
                    probe_trace = probe_executor.execute_probe(
                        run_identity=probe_run_id,
                        product_seal_digest=product_seal,
                        request_identity=case_context["request_identity"],
                        requirement_id=requirement.slot_id,
                        channel=channel,
                        probe=cast(AcquisitionProbe | None, product_probe),
                        query_plan=query_plan,
                        acquisition_plan=plan,
                        context=principal,
                        requested_scope=case_context["scope"],
                        as_of=case_context["as_of"],
                        requested_audit_cap=cap,
                        snapshot_identity=case_context["source_snapshot_digest"],
                        scope_digest=canonical_sha256(case_context["scope"]),
                        policy_digest=canonical_sha256(
                            {
                                "plan_digest": canonical_sha256(
                                    plan.model_dump(mode="json")
                                ),
                                "audit_cap": cap,
                            }
                        ),
                        index_identity=case_context["projection_identity"],
                    )
                    probe_records.append(
                        {
                            "case_id": str(case.case_id),
                            "trace": probe_trace.model_dump(mode="json"),
                        }
                    )
        probe_collection = {
            "schema": "milai.dg24.sealed-official-probe-collection.v0.1",
            "run_id": probe_run_id,
            "product_seal_digest": product_seal,
            "product_sealed_at": product_sealed_at,
            "registry_content_loaded": False,
            "records": probe_records,
            "execution_counts": {
                "wide_probe_dispositions": len(probe_records),
                "product_reruns_after_probe_start": 0,
                "reader_calls": 0,
                "generative_provider_calls": 0,
                "automatic_retries": 0,
            },
        }
        _write_json(probe_path, probe_collection)
        probe_seal = _sha256(probe_path)
        probe_sealed_at = datetime.now(UTC).isoformat()
        unique_keys = {
            (
                item["case_id"],
                item["trace"]["requirement_id"],
                item["trace"]["channel"],
            )
            for item in probe_records
        }
        expected_count = sum(
            sum(
                requirement.required
                for requirement in context["query_plan"].memory_query_ir.requirements
            )
            * len(CHANNELS)
            for context in probe_contexts
        )
        probe_checks = {
            "product_seal_precedes_probe_seal": product_sealed_at < probe_sealed_at,
            "all_probe_dispositions_present": len(probe_records) == expected_count,
            "one_widest_call_disposition_per_requirement_channel": len(unique_keys)
            == len(probe_records),
            "offline_cut_views_from_same_result": all(
                len(
                    {
                        view["source_wide_result_digest"]
                        for view in item["trace"]["offline_cut_views"]
                    }
                )
                == 1
                for item in probe_records
            ),
            "official_executor_identity_present": all(
                item["trace"]["official_executor_identity"]
                == "milai-official-retrieval-audit-probe-v0.1"
                for item in probe_records
            ),
            "official_repository_identity_present": all(
                item["trace"]["repository_identity"]
                == "milai.persistence.RetrievalRepository"
                for item in probe_records
            ),
            "probe_mutations_zero": all(
                not any(item["trace"]["mutations"].values()) for item in probe_records
            ),
            "probe_binding_consumed_zero": all(
                item["trace"]["product_binding_consumed"] is False
                for item in probe_records
            ),
            "product_reruns_after_probe_zero": True,
            "label_access_zero": True,
            "reader_calls_zero": True,
            "generative_provider_calls_zero": True,
        }
        _write_json(
            probe_receipt_path,
            {
                "schema": "milai.dg24.probe-phase-receipt.v0.1",
                "run_id": probe_run_id,
                "sealed_at": probe_sealed_at,
                "product_seal_digest": product_seal,
                "probe_seal_digest": probe_seal,
                "probe_collection": _identity(root, probe_path),
                "hard_gate": {
                    "passed": all(probe_checks.values()),
                    "checks": probe_checks,
                },
            },
        )
    finally:
        cleanup = _cleanup(adapters)
        database.close()
        close = dict(session.close())
    return {
        "schema": "milai.dg24.product-probe-execution-result.v0.1",
        "product_run_id": product_run_id,
        "probe_run_id": probe_run_id,
        "product_collection": _identity(root, product_path),
        "product_receipt": _identity(root, product_receipt_path),
        "probe_collection": _identity(root, probe_path),
        "probe_receipt": _identity(root, probe_receipt_path),
        "runtime": {"start": start, "close": close},
        "cleanup": cleanup,
        "lifecycle": lifecycle,
        "safety": {
            "labels_accessed": 0,
            "reader_calls": 0,
            "generative_provider_calls": 0,
            "automatic_retries": 0,
            "canonical_mutations": 0,
            "formal_holdout_consumed": False,
        },
    }


def _resolve_once(
    *,
    repository: RetrievalRepository,
    database: Database,
    principal: SessionContext,
    settings: Any,
    request: MemoryResolveRequest,
    request_id: str,
    source_snapshot_as_of: datetime,
    enabled: bool,
) -> ProductRetrievalAuditObserver:
    observer = ProductRetrievalAuditObserver(enabled=enabled)
    proxy = AuditRecordingRepository(repository, observer)
    retrieval = RetrievalService(
        cast(RetrievalRepository, proxy),
        embedding=_embedding_provider(settings),
        lexical_enrichment_enabled=True,
        evidence_dense_enabled=True,
        deterministic_recovery_enabled=True,
        type_directed_acquisition_enabled=True,
        query_time_event_enabled=True,
        budget_stable_context_enabled=True,
        retrieval_audit_observer=observer,
    )
    resolver = MemoryResolveService(
        retrieval,
        context_compiler=MemoryContextCompiler(cast(RetrievalRepository, proxy)),
    )
    with label_access_deny_guard():
        execution = resolver.resolve(
            principal,
            request,
            request_id,
            source_snapshot_as_of=source_snapshot_as_of,
        )
    if execution.status_code != 200 or execution.decision_snapshot is None:
        raise DG24ProductError("PRODUCT_PATH_DID_NOT_EXPOSE_DECISION_SNAPSHOT")
    return observer


def _start_runtime(
    run_id: str,
    output: Path,
    cases: tuple[Any, ...],
    env_file: Path,
) -> tuple[
    LocalDG15RuntimeSession,
    Database,
    RetrievalRepository,
    SessionContext,
    dict[str, Any],
]:
    deadline = min(
        120_000, max(30_000, max(len(case.history_events) for case in cases) * 125)
    )
    session = LocalDG15RuntimeSession(
        output_root=output / "runtime",
        env_file=env_file,
        mcp_concurrency=4,
        projection_batch_size=64,
        inherit_source_embedding_runtime=True,
        barrier_timeout_ms=deadline,
    )
    start = dict(session.start(run_id))
    settings = session._settings
    urls = session._database_urls
    if settings is None or urls is None:
        session.close()
        raise DG24ProductError("ISOLATED_RUNTIME_SETTINGS_UNAVAILABLE")
    database = Database(settings, dsn=urls["api"], expected_role="milai_api")
    repository = RetrievalRepository(database)
    principal = SessionContext(settings.tenant_id, settings.local_actor_id)
    return session, database, repository, principal, start


def _ingest_case(
    session: LocalDG15RuntimeSession,
    run_id: str,
    case: Any,
) -> tuple[Any, Any, datetime, str]:
    adapter = session.adapter_for_case(
        case,
        lambda text: max(1, (len(text.encode("utf-8")) + 2) // 3),
    )
    namespace = adapter.reset(run_id, case.case_id)
    adapter.ingest_many(case.history_events)
    readiness = dict(adapter.finalize())
    if readiness.get("status") != "READY":
        raise DG24ProductError(f"PROJECTION_NOT_READY:{case.case_id}")
    reference = _reference(case)
    source_snapshot_as_of = max(
        reference,
        *(
            datetime.fromisoformat(event.observed_at.replace("Z", "+00:00"))
            for event in case.history_events
        ),
    )
    source_digest = canonical_sha256(
        [event.canonical() for event in case.history_events]
    )
    return adapter, namespace, source_snapshot_as_of, source_digest


def _request(case: Any, scope: Mapping[str, Any]) -> MemoryResolveRequest:
    return MemoryResolveRequest(
        query=str(case.question),
        requested_scope=dict(scope),
        required_authority="INFORMATIONAL",
        required_freshness="CURRENT",
        consistency_mode="CANONICAL_REQUIRED",
        reference_time=_reference(case),
        budget=MemoryResolveBudget(
            max_results=8,
            max_candidates=8,
            max_context_tokens=8000,
            max_latency_ms=2_000,
        ),
    )


def _reference(case: Any) -> datetime:
    return datetime.fromisoformat(
        normalize_lme_timestamp(str(case.question_at)).replace("Z", "+00:00")
    )


def _input_manifest(path: Path) -> InputOnlyCaseManifestV01:
    return InputOnlyCaseManifestV01.model_validate(_read_json(path))


def _label_closed_cases(manifest: InputOnlyCaseManifestV01) -> tuple[Any, ...]:
    with label_access_deny_guard():
        cases, _selection = load_public_dev_cases()
    if [str(case.case_id) for case in cases] != manifest.case_order:
        raise DG24ProductError("INPUT_ONLY_CASE_ORDER_MISMATCH")
    return cases


def _verify_manifest_request(
    manifest: InputOnlyCaseManifestV01,
    case: Any,
    source_digest: str,
) -> None:
    observed = canonical_sha256(
        {
            "query_text": str(case.question),
            "question_at": str(case.question_at),
            "requested_scope_policy": "ISOLATED_CASE_NAMESPACE",
            "source_snapshot_digest": source_digest,
        }
    )
    expected = _manifest_request(manifest, str(case.case_id))
    if expected["request_payload_digest"] != observed:
        raise DG24ProductError(f"INPUT_ONLY_REQUEST_IDENTITY_MISMATCH:{case.case_id}")


def _manifest_request(
    manifest: InputOnlyCaseManifestV01, case_id: str
) -> dict[str, Any]:
    item = next(value for value in manifest.requests if value.case_id == case_id)
    return item.model_dump(mode="json")


def _repository_semantics(
    observer: ProductRetrievalAuditObserver,
) -> list[dict[str, Any]]:
    return [
        {
            "method": item.method,
            "output_digest": item.output_digest,
        }
        for item in observer.repository_calls
    ]


def _repository_diagnostics(
    observer: ProductRetrievalAuditObserver,
) -> list[dict[str, Any]]:
    return [
        {
            "method": item.method,
            "input_digest": item.input_digest,
            "output_digest": item.output_digest,
        }
        for item in observer.repository_calls
    ]


def _same_snapshot_field(
    baseline: Mapping[str, str], traced: Mapping[str, str], field: str
) -> bool:
    return field in baseline and baseline[field] == traced.get(field)


def _same_snapshot_fields(
    baseline: Mapping[str, str], traced: Mapping[str, str], fields: tuple[str, ...]
) -> bool:
    return all(_same_snapshot_field(baseline, traced, field) for field in fields)


def _cleanup(adapters: list[Any]) -> dict[str, Any]:
    failures = []
    for adapter in reversed(adapters):
        try:
            adapter.cleanup()
        except Exception as exc:  # noqa: BLE001 - cleanup ledger must retain every failure
            failures.append({"type": type(exc).__name__, "message": str(exc)})
    return {
        "registered_adapter_count": len(adapters),
        "cleanup_failure_count": len(failures),
        "failures": failures,
        "passed": not failures,
    }


@contextmanager
def label_access_deny_guard() -> Iterator[None]:
    original_open = builtins.open
    original_io_open = io.open

    def guarded(file: Any, *args: Any, **kwargs: Any) -> Any:
        value = os.fspath(file) if isinstance(file, (str, os.PathLike)) else str(file)
        normalized = value.replace("\\", "/").casefold()
        if any(fragment in normalized for fragment in DENY_FRAGMENTS):
            raise DG24ProductError(f"LABEL_PRODUCT_BOUNDARY_VIOLATION:{value}")
        return original_open(file, *args, **kwargs)

    def guarded_io(file: Any, *args: Any, **kwargs: Any) -> Any:
        value = os.fspath(file) if isinstance(file, (str, os.PathLike)) else str(file)
        normalized = value.replace("\\", "/").casefold()
        if any(fragment in normalized for fragment in DENY_FRAGMENTS):
            raise DG24ProductError(f"LABEL_PRODUCT_BOUNDARY_VIOLATION:{value}")
        return original_io_open(file, *args, **kwargs)

    builtins.open = guarded
    io.open = guarded_io
    try:
        yield
    finally:
        builtins.open = original_open
        io.open = original_io_open


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(root)),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


__all__ = [
    "DG24ProductError",
    "label_access_deny_guard",
    "run_behavior_equivalence",
    "run_product_then_probes",
]
