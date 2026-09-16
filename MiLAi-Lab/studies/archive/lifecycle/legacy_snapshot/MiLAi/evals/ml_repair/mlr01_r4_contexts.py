"""Four-arm context execution for the ML-R01 R4 staircase.

The two product arms ingest each case exactly once.  OFF and CANARY APIs share
the same ephemeral shard database, tenant, project, Evidence identities, worker
and finalized watermark; only their read policy differs.
"""

from __future__ import annotations

import hashlib
import os
import resource
import subprocess
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from tokenizers import Tokenizer

from evals.dg14.contracts import (
    DG14ContractError,
    DG14ReadinessError,
    normalize_lme_timestamp,
    validate_label_free,
)
from evals.dg15.contracts import DG15AdapterConfig, DG15QueryResult
from evals.dg15.mcp_stdio import MultiplexedStdioMcpTransport
from evals.dg15.runtime_session import LocalDG15RuntimeSession
from evals.ml_closure.longmemeval_contexts import (
    ContextExecutionSpec,
    _case_snapshot_identity,
    _ClosureAdapter,
    _failure_record,
    _safe_mapping,
    _shard_cleanup_witness,
    _success_record,
    _technical_shard_cleanup_witness,
    _token_counter,
)
from evals.ml_closure.longmemeval_contract import (
    case_subject,
    history_events,
    runtime_case_id,
)
from evals.ml_repair.mlr01_r4_contract import (
    ARMS,
    CAPABILITY_SEAL_PATH,
    CONTEXT_RESOURCE_WINDOW_SECONDS,
    CONTRIEVER_PYTHON,
    CPU_WORKERS,
    DENSE_SHARDS,
    MEMORY_TOKEN_BUDGET,
    PRODUCT_ARMS,
    R4_ROOT,
    ROOT,
    RUN_ID,
    RUN_ROOT,
    SCHEMA_VERSION,
    STATEFUL_SHARDS,
    TOKENIZER_PATH,
    MLR01R4Error,
    atomic_json,
    canonical_sha256,
    capability_seal_digest,
    context_path,
    load_json,
    product_pair_path,
    records_sha256,
    require_stage_seal,
    sha256_file,
    source_snapshot_sha256,
    stage_seal_path,
    target_case_ids,
    target_cases,
    valid_terminal,
)
from evals.paper.adapters import OfficialBM25Adapter
from evals.paper.runners.longmemeval import memory_events

BM25_ARM = "MLR01-BM25-T"
DENSE_ARM = "MLR01-DENSE"
RAW_ARM = "MLR01-R"
FORMED_ARM = "MLR01-F"
RUN_LOCK_DIGEST = sha256_file(RUN_ROOT / "run-lock.json")
AMENDMENT_DIGEST = sha256_file(RUN_ROOT / "protocol-amendment.json")

PRODUCT_SPEC = ContextExecutionSpec(
    run_id=RUN_ID,
    checkpoint_root=R4_ROOT,
    arms=PRODUCT_ARMS,
    arm_modes=((RAW_ARM, "OFF"), (FORMED_ARM, "CANARY")),
    run_lock_digest=RUN_LOCK_DIGEST,
    stateful_shards=STATEFUL_SHARDS,
    mcp_concurrency=4,
    projection_batch_size=32,
    barrier_timeout_ms=120_000,
    max_results=12,
    memory_token_budget=MEMORY_TOKEN_BUDGET,
    max_latency_ms=2_000,
    cleanup_barrier_timeout_ms=300_000,
    shard_lifecycle_mode="SHARD_TERMINAL_CLEANUP_WITNESS",
    protocol_amendment_digest=AMENDMENT_DIGEST,
    progressive_context_evidence=True,
)


class _PairedLocalDG15RuntimeSession(LocalDG15RuntimeSession):
    """One CANARY API plus one OFF read API over the same shard database."""

    def __init__(self, *, output_root: Path) -> None:
        super().__init__(
            output_root=output_root / "formed",
            mcp_concurrency=4,
            projection_batch_size=32,
            barrier_timeout_ms=120_000,
            memory_formation_mode="CANARY",
            progressive_context_evidence=True,
        )
        self._raw_api_process: subprocess.Popen[bytes] | None = None
        self._raw_runtime_log: Any = None
        self._raw_settings: Any = None

    def start(self, run_id: str) -> Mapping[str, Any]:
        details = dict(super().start(run_id))
        if (
            self._settings is None
            or self._database_urls is None
            or self._tokens is None
        ):
            raise RuntimeError("paired Runtime state is absent after CANARY startup")
        from milai.config.settings import prepare_runtime_directories
        from milai.operations.smoke import (
            _api_environment,
            _free_loopback_port,
            _HttpClient,
            _wait_api,
        )

        raw_settings = self._settings.model_copy(
            update={
                "bind_port": _free_loopback_port(),
                "feature_profile": "BASELINE",
                "progressive_context_evidence_v0_1": False,
            }
        )
        prepare_runtime_directories(raw_settings)
        environment = _api_environment(raw_settings, self._database_urls, self._tokens)
        environment["MILAI_DATA_MODE"] = "DEIDENTIFIED_ALLOWED"
        raw_root = self.output_root.parent / "raw"
        raw_root.mkdir(parents=True, exist_ok=True)
        raw_log = (raw_root / "runtime.log").open("wb")
        process = subprocess.Popen(
            [str(self.project_root / "runtime/.venv/bin/milai-api")],
            cwd=self.project_root / "runtime",
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=raw_log,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_api(
                _HttpClient(
                    f"http://{raw_settings.bind_host}:{raw_settings.bind_port}"
                ),
                process,
            )
        except (OSError, RuntimeError):
            process.terminate()
            process.wait(timeout=10)
            raw_log.close()
            raise
        self._raw_api_process = process
        self._raw_runtime_log = raw_log
        self._raw_settings = raw_settings
        details.update(
            {
                "paired_raw_api": True,
                "raw_api_base_url": (
                    f"http://{raw_settings.bind_host}:{raw_settings.bind_port}"
                ),
                "shared_database_exact": True,
                "raw_mode": "OFF",
                "formed_mode": "CANARY",
                "progressive_context_evidence": True,
            }
        )
        return details

    def raw_adapter_config(self) -> DG15AdapterConfig:
        if self._raw_settings is None:
            raise RuntimeError("raw Runtime adapter requested before startup")
        return replace(
            self.adapter_config(),
            base_url=(
                f"http://{self._raw_settings.bind_host}:{self._raw_settings.bind_port}"
            ),
            formation_mode="OFF",
        )

    def raw_api_status(self) -> Mapping[str, Any]:
        process = self._raw_api_process
        return {
            "status": (
                "NOT_STARTED"
                if process is None
                else ("RUNNING" if process.poll() is None else "EXITED")
            ),
            "return_code": process.poll() if process is not None else None,
        }

    def close(self) -> Mapping[str, Any]:
        from milai.operations.smoke import _stop_api

        raw = self._raw_api_process
        self._raw_api_process = None
        raw_result: dict[str, Any]
        if raw is None:
            raw_result = {"status": "NOT_STARTED"}
        else:
            _stop_api(raw)
            raw_result = {"status": "STOPPED", "return_code": raw.poll()}
        if self._raw_runtime_log is not None:
            self._raw_runtime_log.close()
            self._raw_runtime_log = None
        self._raw_settings = None
        result = dict(super().close())
        result["paired_raw_api"] = raw_result
        return result


def _bm25_one(case: Any, *, seal_digest: str, counter: Any) -> dict[str, Any]:
    path = context_path(BM25_ARM, case.source_id)
    prior = valid_terminal(
        path,
        schema_suffix="context",
        arm=BM25_ARM,
        case_id=case.source_id,
        seal_digest=seal_digest,
    )
    if prior is not None and prior.get("terminal_status") == "SUCCEEDED":
        return dict(prior)
    try:
        adapter = OfficialBM25Adapter(
            granularity="turn", top_k=3, token_counter=counter
        )
        adapter.reset(RUN_ID, case.source_id)
        for event in memory_events(case):
            adapter.ingest(event)
        adapter.finalize()
        result = adapter.query(
            case.question, case.question_at, MEMORY_TOKEN_BUDGET, "CONTROLLED"
        )
        context = result.context
        record: dict[str, Any] = {
            "schema": f"{SCHEMA_VERSION}.context-terminal",
            "run_id": RUN_ID,
            "capability_seal_digest": seal_digest,
            "case_id": case.source_id,
            "category": case.category,
            "arm": BM25_ARM,
            "track": "EVALUATION_BASELINE_NO_CANONICAL_AUTHORITY",
            "terminal_status": "SUCCEEDED",
            "context": context,
            "context_sha256": hashlib.sha256(context.encode()).hexdigest(),
            "context_tokens": int(result.declared_tokens),
            "retrieval_trace": [dict(value) for value in result.trace],
            "selected_session_ids": list(
                dict.fromkeys(str(value["session_id"]) for value in result.trace)
            ),
            "source_input_snapshot_digest": source_snapshot_sha256(case),
            "history_session_count": len(case.sessions),
            "history_turn_count": sum(len(session.turns) for session in case.sessions),
            "labels_opened_by_context_worker": False,
            "answer_or_answer_session_fields_accessed": False,
            "canonical_authority": False,
            "canonical_mutation": False,
            "provider_calls": {"answer": 0, "judge": 0},
            "usage": {
                **dict(result.usage),
                "adapter_storage_bytes": adapter.stats().storage_bytes,
                "official_style": "BM25_OKAPI_0.2.2_SPLIT_LITERAL_SPACE",
                "granularity": "turn",
                "top_k": 3,
            },
            "latency_ms": round(float(result.latency_ms), 6),
        }
    except Exception as exc:  # noqa: BLE001 - one cell becomes terminal
        record = {
            "schema": f"{SCHEMA_VERSION}.context-terminal",
            "run_id": RUN_ID,
            "capability_seal_digest": seal_digest,
            "case_id": case.source_id,
            "category": case.category,
            "arm": BM25_ARM,
            "track": "EVALUATION_BASELINE_NO_CANONICAL_AUTHORITY",
            "terminal_status": "FAILED",
            "context": "",
            "context_sha256": hashlib.sha256(b"").hexdigest(),
            "context_tokens": 0,
            "retrieval_trace": [],
            "selected_session_ids": [],
            "source_input_snapshot_digest": source_snapshot_sha256(case),
            "labels_opened_by_context_worker": False,
            "answer_or_answer_session_fields_accessed": False,
            "canonical_authority": False,
            "canonical_mutation": False,
            "provider_calls": {"answer": 0, "judge": 0},
            "failure_class": type(exc).__name__,
            "failure_message_sha256": hashlib.sha256(str(exc).encode()).hexdigest(),
        }
    atomic_json(path, record)
    return record


def run_bm25(target_count: int) -> dict[str, Any]:
    seal_digest = capability_seal_digest()
    tokenizer = Tokenizer.from_file(str(TOKENIZER_PATH))
    counter = lambda text: len(tokenizer.encode(text).ids)
    cases = target_cases(target_count)
    started = time.perf_counter()
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=CPU_WORKERS) as executor:
        futures = {
            executor.submit(
                _bm25_one, case, seal_digest=seal_digest, counter=counter
            ): case.source_id
            for case in cases
        }
        for future in as_completed(futures):
            records.append(future.result())
    terminal = {
        "schema": f"{SCHEMA_VERSION}.bm25-terminal",
        "run_id": RUN_ID,
        "capability_seal_digest": seal_digest,
        "target_count": target_count,
        "arm": BM25_ARM,
        "workers": CPU_WORKERS,
        "terminal_count": len(records),
        "succeeded": sum(
            record["terminal_status"] == "SUCCEEDED" for record in records
        ),
        "failed": sum(record["terminal_status"] == "FAILED" for record in records),
        "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
    }
    atomic_json(R4_ROOT / "runtime" / f"bm25-{target_count}.json", terminal)
    return terminal


def run_dense(target_count: int) -> tuple[dict[str, Any], ...]:
    if not CONTRIEVER_PYTHON.is_file():
        raise MLR01R4Error("frozen Contriever Python environment is absent")
    processes: list[tuple[int, subprocess.Popen[bytes], Any]] = []
    for shard in range(DENSE_SHARDS):
        log_path = R4_ROOT / "runtime" / f"dense-{target_count}-shard-{shard}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = log_path.open("wb")
        process = subprocess.Popen(
            [
                str(CONTRIEVER_PYTHON),
                "-m",
                "evals.ml_repair.mlr01_r4_dense",
                "--target",
                str(target_count),
                "--shard",
                str(shard),
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        processes.append((shard, process, log))
    failures: list[str] = []
    for shard, process, log in processes:
        return_code = process.wait()
        log.close()
        if return_code != 0:
            failures.append(f"shard-{shard}:exit-{return_code}")
    if failures:
        raise MLR01R4Error("dense context workers failed: " + ",".join(failures))
    return tuple(
        cast(
            dict[str, Any],
            load_json(R4_ROOT / "runtime" / f"dense-{target_count}-shard-{shard}.json"),
        )
        for shard in range(DENSE_SHARDS)
    )


def _raw_query(
    *,
    adapter: _ClosureAdapter,
    transport: MultiplexedStdioMcpTransport,
    question: str,
    question_at: str,
    budget: int,
    task_context: Mapping[str, object],
) -> DG15QueryResult:
    """Consume the OFF MCP response using the same governed adapter checks."""

    validate_label_free(task_context, path="query.task_context")
    projects = task_context.get("project_ids")
    if projects != [adapter.namespace.project_id]:
        raise DG14ContractError("raw TaskContext project scope differs from case")
    transport.open_case(adapter.namespace.scope)
    started = time.perf_counter()
    response = transport.call(
        "reader-detail",
        "milai_memory_resolve",
        {
            "query": f"Recall previous history evidence: {question}",
            "required_freshness": "CURRENT",
            "consistency_mode": "CANONICAL_REQUIRED",
            "limit": 12,
            "max_context_tokens": budget,
            "max_latency_ms": 2_000,
            "reference_time": normalize_lme_timestamp(question_at),
            "task_context": dict(task_context),
        },
    )
    status = adapter._validate_resolve(response)
    resolved = adapter._resolved_evidence(response)
    packed = adapter._runtime_context(response, budget)
    provenance = adapter._provenance(resolved, packed.selected_sessions)
    elapsed_ms = (time.perf_counter() - started) * 1_000
    return DG15QueryResult(
        method_id=RAW_ARM,
        status=status,
        context=packed.text,
        source_ids=tuple(item.session_id for item in provenance[:3]),
        selected_source_refs=packed.selected_source_refs,
        provenance=provenance,
        stage_trace=(),
        declared_tokens=packed.tokens,
        latency_ms=elapsed_ms,
        usage={
            "logical_mcp_calls": 1,
            "physical_mcp_batches": 1,
            "retrieval_ms": elapsed_ms,
            "context_compile_ms": 0.0,
            "fallback_used": response.get("fallback_used") is True,
            "retrieval_terminal_stage": adapter._terminal_stage(response),
        },
        raw_resolve=response,
    )


def _product_record(
    record: dict[str, Any],
    *,
    seal_digest: str,
    case: Any,
    pair_snapshot_digest: str,
    other_context_sha256: str,
) -> dict[str, Any]:
    record.update(
        {
            "schema": f"{SCHEMA_VERSION}.context-terminal",
            "capability_seal_digest": seal_digest,
            "source_input_snapshot_digest": source_snapshot_sha256(case),
            "paired_product_snapshot_digest": pair_snapshot_digest,
            "paired_other_context_sha256": other_context_sha256,
            "paired_snapshot_identity_exact": True,
            "paired_evidence_watermark_exact": True,
            "paired_ingest_count": 1,
            "paired_resolve_count": 2,
            "mutation_between_paired_reads": False,
            "labels_opened_by_context_worker": False,
            "answer_or_answer_session_fields_accessed": False,
            "canonical_authority": True,
            "canonical_mutation": False,
            "question_visible_to_ingest_or_formation_build": False,
            "question_visible_to_retrieval_selection": True,
        }
    )
    record.pop("question_visible_to_ingest_or_formation", None)
    return record


def _write_product_pair(
    *,
    case: Any,
    raw: dict[str, Any],
    formed: dict[str, Any],
    seal_digest: str,
) -> dict[str, Any]:
    raw_digest = canonical_sha256(raw)
    formed_digest = canonical_sha256(formed)
    pair = {
        "schema": f"{SCHEMA_VERSION}.product-pair-terminal",
        "run_id": RUN_ID,
        "capability_seal_digest": seal_digest,
        "case_id": case.source_id,
        "terminal_status": (
            "SUCCEEDED"
            if raw.get("terminal_status")
            == formed.get("terminal_status")
            == "SUCCEEDED"
            else "FAILED"
        ),
        "source_input_snapshot_digest": source_snapshot_sha256(case),
        "paired_product_snapshot_digest": raw.get("paired_product_snapshot_digest"),
        "raw_record_sha256": raw_digest,
        "formed_record_sha256": formed_digest,
        "snapshot_identity_exact": (
            raw.get("paired_product_snapshot_digest")
            == formed.get("paired_product_snapshot_digest")
        ),
        "watermark_identity_exact": (
            _safe_mapping(raw.get("snapshot")).get("resolve_evidence_watermark")
            == _safe_mapping(formed.get("snapshot")).get("resolve_evidence_watermark")
        ),
        "one_ingest_two_reads": True,
        "canonical_mutation": False,
    }
    atomic_json(context_path(RAW_ARM, case.source_id), raw)
    atomic_json(context_path(FORMED_ARM, case.source_id), formed)
    atomic_json(product_pair_path(case.source_id), pair)
    return pair


def _valid_product_pair(case_id: str, seal_digest: str) -> bool:
    raw = valid_terminal(
        context_path(RAW_ARM, case_id),
        schema_suffix="context",
        arm=RAW_ARM,
        case_id=case_id,
        seal_digest=seal_digest,
    )
    formed = valid_terminal(
        context_path(FORMED_ARM, case_id),
        schema_suffix="context",
        arm=FORMED_ARM,
        case_id=case_id,
        seal_digest=seal_digest,
    )
    if raw is None or formed is None or not product_pair_path(case_id).is_file():
        return False
    pair = load_json(product_pair_path(case_id))
    return bool(
        isinstance(pair, dict)
        and pair.get("schema") == f"{SCHEMA_VERSION}.product-pair-terminal"
        and pair.get("capability_seal_digest") == seal_digest
        and pair.get("case_id") == case_id
        and pair.get("terminal_status") == "SUCCEEDED"
        and raw.get("terminal_status") == "SUCCEEDED"
        and formed.get("terminal_status") == "SUCCEEDED"
        and pair.get("raw_record_sha256") == canonical_sha256(raw)
        and pair.get("formed_record_sha256") == canonical_sha256(formed)
        and pair.get("snapshot_identity_exact") is True
        and pair.get("watermark_identity_exact") is True
    )


def _run_product_case(
    *,
    session: _PairedLocalDG15RuntimeSession,
    case: Any,
    shard: int,
    seal_digest: str,
    counter: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    formed_config = replace(
        session.adapter_config(),
        max_limit=12,
        allowed_budgets=(MEMORY_TOKEN_BUDGET,),
        project_prefix="mlc-lme",
        barrier_timeout_ms=120_000,
        max_latency_ms=2_000,
    )
    raw_config = replace(
        session.raw_adapter_config(),
        max_limit=12,
        allowed_budgets=(MEMORY_TOKEN_BUDGET,),
        project_prefix="mlc-lme",
        barrier_timeout_ms=120_000,
        max_latency_ms=2_000,
    )
    runtime_root = R4_ROOT / "runtime" / "product-mcp" / f"shard-{shard}"
    runtime_root.mkdir(parents=True, exist_ok=True)
    formed_log = (runtime_root / "formed-mcp.log").open("ab")
    raw_log = (runtime_root / "raw-mcp.log").open("ab")
    formed_transport = MultiplexedStdioMcpTransport(
        formed_config.dg14_config(), stderr=formed_log
    )
    raw_transport = MultiplexedStdioMcpTransport(
        raw_config.dg14_config(), stderr=raw_log
    )
    adapter = _ClosureAdapter(
        formed_config,
        token_counter=counter,
        transport=formed_transport,
        close_transport_on_cleanup=False,
    )
    started = time.perf_counter()
    try:
        reset_started = time.perf_counter()
        private_case_id = runtime_case_id(case.source_id)
        namespace = adapter.reset(RUN_ID, private_case_id)
        reset_ms = (time.perf_counter() - reset_started) * 1_000
        ingest_started = time.perf_counter()
        adapter.ingest_many(history_events(case))
        ingest_ms = (time.perf_counter() - ingest_started) * 1_000
        barrier_started = time.perf_counter()
        finalize = adapter.finalize()
        barrier_ms = (time.perf_counter() - barrier_started) * 1_000
        task_context = {
            "project_ids": [namespace.project_id],
            "entities": [case_subject(namespace.project_id, private_case_id)],
        }
        raw_started = time.perf_counter()
        raw_result = _raw_query(
            adapter=adapter,
            transport=raw_transport,
            question=case.question,
            question_at=case.question_at,
            budget=MEMORY_TOKEN_BUDGET,
            task_context=task_context,
        )
        raw_ms = (time.perf_counter() - raw_started) * 1_000
        formed_started = time.perf_counter()
        formed_result = adapter.query(
            case.question,
            case.question_at,
            MEMORY_TOKEN_BUDGET,
            task_context=task_context,
        )
        formed_ms = (time.perf_counter() - formed_started) * 1_000
        receipts = adapter.export_governance_receipts()
        raw_snapshot = _case_snapshot_identity(
            project_id=namespace.project_id,
            receipts=receipts,
            finalize=finalize,
            raw_resolve=_safe_mapping(raw_result.raw_resolve),
            formation_mode="OFF",
        )
        formed_snapshot = _case_snapshot_identity(
            project_id=namespace.project_id,
            receipts=receipts,
            finalize=finalize,
            raw_resolve=_safe_mapping(formed_result.raw_resolve),
            formation_mode="CANARY",
        )
        if (
            raw_snapshot.get("identity_sha256")
            != formed_snapshot.get("identity_sha256")
            or raw_snapshot.get("resolve_evidence_watermark")
            != formed_snapshot.get("resolve_evidence_watermark")
            or raw_snapshot.get("watermark_identity_exact") is not True
            or formed_snapshot.get("watermark_identity_exact") is not True
        ):
            raise DG14ReadinessError("paired OFF/CANARY Evidence snapshot drifted")
        pair_snapshot_digest = canonical_sha256(
            {
                "identity_sha256": raw_snapshot["identity_sha256"],
                "evidence_watermark": raw_snapshot["resolve_evidence_watermark"],
                "source_input_snapshot_digest": source_snapshot_sha256(case),
            }
        )
        cleanup = {
            "mode": "SHARD_TERMINAL_CLEANUP_WITNESS",
            "deferred_to_shard": True,
        }
        raw_record = _success_record(
            spec=PRODUCT_SPEC,
            arm=RAW_ARM,
            case=case,
            shard=shard,
            run_lock_digest=RUN_LOCK_DIGEST,
            result=raw_result,
            receipts=receipts,
            timings={
                "reset": reset_ms,
                "ingest": ingest_ms,
                "index_barrier": barrier_ms,
                "query_and_context": raw_ms,
                "paired_other_query_and_context": formed_ms,
                "cleanup_submission": 0.0,
                "case_wall": (time.perf_counter() - started) * 1_000,
            },
            cleanup=cleanup,
            snapshot=raw_snapshot,
        )
        formed_record = _success_record(
            spec=PRODUCT_SPEC,
            arm=FORMED_ARM,
            case=case,
            shard=shard,
            run_lock_digest=RUN_LOCK_DIGEST,
            result=formed_result,
            receipts=receipts,
            timings={
                "reset": reset_ms,
                "ingest": ingest_ms,
                "index_barrier": barrier_ms,
                "query_and_context": formed_ms,
                "paired_other_query_and_context": raw_ms,
                "cleanup_submission": 0.0,
                "case_wall": (time.perf_counter() - started) * 1_000,
            },
            cleanup=cleanup,
            snapshot=formed_snapshot,
        )
        raw_record = _product_record(
            raw_record,
            seal_digest=seal_digest,
            case=case,
            pair_snapshot_digest=pair_snapshot_digest,
            other_context_sha256=str(formed_record["context_sha256"]),
        )
        formed_record = _product_record(
            formed_record,
            seal_digest=seal_digest,
            case=case,
            pair_snapshot_digest=pair_snapshot_digest,
            other_context_sha256=str(raw_record["context_sha256"]),
        )
        pair = _write_product_pair(
            case=case,
            raw=raw_record,
            formed=formed_record,
            seal_digest=seal_digest,
        )
        return raw_record, formed_record, pair
    except Exception as exc:  # noqa: BLE001 - paired cell becomes terminal
        elapsed = (time.perf_counter() - started) * 1_000
        raw_record = _failure_record(
            spec=PRODUCT_SPEC,
            arm=RAW_ARM,
            case=case,
            shard=shard,
            run_lock_digest=RUN_LOCK_DIGEST,
            error=exc,
            elapsed_ms=elapsed,
            cleanup={
                "mode": "SHARD_TERMINAL_CLEANUP_WITNESS",
                "deferred_to_shard": True,
            },
        )
        formed_record = _failure_record(
            spec=PRODUCT_SPEC,
            arm=FORMED_ARM,
            case=case,
            shard=shard,
            run_lock_digest=RUN_LOCK_DIGEST,
            error=exc,
            elapsed_ms=elapsed,
            cleanup={
                "mode": "SHARD_TERMINAL_CLEANUP_WITNESS",
                "deferred_to_shard": True,
            },
        )
        failure_pair_digest = canonical_sha256(
            {
                "case_id": case.source_id,
                "failure_class": type(exc).__name__,
                "source_input_snapshot_digest": source_snapshot_sha256(case),
            }
        )
        raw_record = _product_record(
            raw_record,
            seal_digest=seal_digest,
            case=case,
            pair_snapshot_digest=failure_pair_digest,
            other_context_sha256=hashlib.sha256(b"").hexdigest(),
        )
        formed_record = _product_record(
            formed_record,
            seal_digest=seal_digest,
            case=case,
            pair_snapshot_digest=failure_pair_digest,
            other_context_sha256=hashlib.sha256(b"").hexdigest(),
        )
        pair = _write_product_pair(
            case=case,
            raw=raw_record,
            formed=formed_record,
            seal_digest=seal_digest,
        )
        return raw_record, formed_record, pair
    finally:
        try:
            raw_transport.close()
        finally:
            try:
                formed_transport.close()
            finally:
                raw_log.close()
                formed_log.close()


def run_product_shard(*, target_count: int, shard: int) -> dict[str, Any]:
    if not 0 <= shard < STATEFUL_SHARDS:
        raise ValueError("product shard is invalid")
    seal_digest = capability_seal_digest()
    cases = tuple(
        case
        for ordinal, case in enumerate(target_cases(target_count))
        if ordinal % STATEFUL_SHARDS == shard
    )
    pending = [
        case for case in cases if not _valid_product_pair(case.source_id, seal_digest)
    ]
    terminal_path = R4_ROOT / "runtime" / f"product-{target_count}-shard-{shard}.json"
    if not pending and terminal_path.is_file():
        prior_terminal = load_json(terminal_path)
        if (
            isinstance(prior_terminal, dict)
            and prior_terminal.get("schema")
            == f"{SCHEMA_VERSION}.product-shard-terminal"
            and prior_terminal.get("capability_seal_digest") == seal_digest
            and prior_terminal.get("target_count") == target_count
            and prior_terminal.get("shard") == shard
            and prior_terminal.get("failed_cells") == 0
            and prior_terminal.get("shard_cleanup_witness", {}).get("status") == "PASS"
            and prior_terminal.get("runtime_cleanup", {}).get("status") == "PASS"
        ):
            return dict(prior_terminal)
    started = time.perf_counter()
    session = _PairedLocalDG15RuntimeSession(
        output_root=R4_ROOT / "runtime" / f"product-{target_count}" / f"shard-{shard}"
    )
    runtime: Mapping[str, Any] = {"status": "NOT_STARTED"}
    worker: Mapping[str, Any] = {"status": "NOT_STARTED"}
    raw_api: Mapping[str, Any] = {"status": "NOT_STARTED"}
    projection_metrics: Mapping[str, Any] = {"status": "NOT_COLLECTED"}
    cleanup_witness: Mapping[str, Any] = {"status": "NOT_REQUIRED"}
    runtime_cleanup: Mapping[str, Any] = {"status": "NOT_CREATED"}
    executed_successes: list[Any] = []
    if pending or cases:
        try:
            runtime = session.start(f"{RUN_ID}-r4-{target_count}-shard-{shard}")
            counter = _token_counter()
            for case in pending:
                _raw, _formed, pair = _run_product_case(
                    session=session,
                    case=case,
                    shard=shard,
                    seal_digest=seal_digest,
                    counter=counter,
                )
                if pair.get("terminal_status") == "SUCCEEDED":
                    executed_successes.append(case)
            witness_case = executed_successes[-1] if executed_successes else None
            try:
                if witness_case is not None:
                    cleanup_witness = _shard_cleanup_witness(
                        spec=PRODUCT_SPEC,
                        session=session,
                        case_id=witness_case.source_id,
                        evidence_count=len(history_events(witness_case)),
                    )
                else:
                    cleanup_witness = _technical_shard_cleanup_witness(
                        spec=PRODUCT_SPEC,
                        session=session,
                        shard=shard,
                    )
            except Exception as exc:  # noqa: BLE001
                cleanup_witness = {
                    "status": "FAILED",
                    "failure_class": type(exc).__name__,
                    "failure_message_sha256": hashlib.sha256(
                        str(exc).encode()
                    ).hexdigest(),
                }
        finally:
            worker = session.worker_status()
            raw_api = session.raw_api_status()
            try:
                projection_metrics = session.projection_metrics()
            except Exception as exc:  # noqa: BLE001
                projection_metrics = {
                    "status": "FAILED",
                    "failure_class": type(exc).__name__,
                    "failure_message_sha256": hashlib.sha256(
                        str(exc).encode()
                    ).hexdigest(),
                }
            runtime_cleanup = session.close()
    records = [
        valid_terminal(
            context_path(arm, case.source_id),
            schema_suffix="context",
            arm=arm,
            case_id=case.source_id,
            seal_digest=seal_digest,
        )
        for case in cases
        for arm in PRODUCT_ARMS
    ]
    failed_records = sum(
        record is None or record.get("terminal_status") != "SUCCEEDED"
        for record in records
    )
    terminal = {
        "schema": f"{SCHEMA_VERSION}.product-shard-terminal",
        "run_id": RUN_ID,
        "capability_seal_digest": seal_digest,
        "target_count": target_count,
        "shard": shard,
        "case_count": len(cases),
        "cell_count": len(cases) * 2,
        "resumed_pairs": len(cases) - len(pending),
        "executed_pairs": len(pending),
        "succeeded_cells": len(records) - failed_records,
        "failed_cells": failed_records,
        "runtime": dict(runtime),
        "worker": dict(worker),
        "raw_api": dict(raw_api),
        "projection_metrics": dict(projection_metrics),
        "shard_cleanup_witness": dict(cleanup_witness),
        "runtime_cleanup": dict(runtime_cleanup),
        "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "process_id": os.getpid(),
    }
    atomic_json(terminal_path, terminal)
    return terminal


def run_product(target_count: int) -> tuple[dict[str, Any], ...]:
    terminals: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=STATEFUL_SHARDS) as executor:
        futures = {
            executor.submit(
                run_product_shard, target_count=target_count, shard=shard
            ): shard
            for shard in range(STATEFUL_SHARDS)
        }
        for future in as_completed(futures):
            terminals.append(future.result())
    return tuple(sorted(terminals, key=lambda value: int(value["shard"])))


def load_context_records(target_count: int) -> tuple[dict[str, Any], ...]:
    seal_digest = capability_seal_digest()
    records: list[dict[str, Any]] = []
    for case_id in target_case_ids(target_count):
        for arm in ARMS:
            record = valid_terminal(
                context_path(arm, case_id),
                schema_suffix="context",
                arm=arm,
                case_id=case_id,
                seal_digest=seal_digest,
            )
            if record is None:
                raise MLR01R4Error(f"R4 context terminal is missing: {case_id}/{arm}")
            records.append(dict(record))
    return tuple(records)


def seal_contexts(
    *,
    target_count: int,
    stage_started: float,
    bm25: Mapping[str, Any],
    dense: Sequence[Mapping[str, Any]],
    product: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    seal_digest = capability_seal_digest()
    records = load_context_records(target_count)
    by_arm = {
        arm: [record for record in records if record["arm"] == arm] for arm in ARMS
    }
    f_rows = by_arm[FORMED_ARM]
    product_snapshot_failures = sum(
        record.get("paired_snapshot_identity_exact") is not True
        or record.get("paired_evidence_watermark_exact") is not True
        for arm in PRODUCT_ARMS
        for record in by_arm[arm]
    )
    formation_rows = [
        cast(Mapping[str, Any], record.get("formation") or {}) for record in f_rows
    ]
    product_runtime_failures = sum(
        terminal.get("worker", {}).get("status") != "RUNNING"
        or terminal.get("raw_api", {}).get("status") != "RUNNING"
        or terminal.get("runtime_cleanup", {}).get("status") != "PASS"
        or terminal.get("shard_cleanup_witness", {}).get("status") != "PASS"
        or terminal.get("projection_metrics", {}).get("status") == "FAILED"
        for terminal in product
    )
    context_wall_seconds = time.perf_counter() - stage_started
    projected_500_seconds = (
        context_wall_seconds
        if target_count == 500
        else context_wall_seconds * 500 / target_count
    )
    failure_classes = Counter(
        str(record.get("failure_class"))
        for record in records
        if record.get("terminal_status") != "SUCCEEDED"
    )
    gate = {
        "all_arm_denominators_complete": all(
            len(by_arm[arm]) == target_count for arm in ARMS
        ),
        "all_context_cells_succeeded": all(
            record.get("terminal_status") == "SUCCEEDED" for record in records
        ),
        "product_delivery_success_1": all(
            record.get("terminal_status") == "SUCCEEDED"
            for arm in PRODUCT_ARMS
            for record in by_arm[arm]
        ),
        "product_snapshot_identity_exact": product_snapshot_failures == 0,
        "product_execution_failures_zero": product_runtime_failures == 0,
        "isolation_safety_violations_zero": all(
            int(record.get("cross_case_evidence_leak") or 0) == 0
            and int(record.get("authority_scope_revocation_violation") or 0) == 0
            and record.get("canonical_mutation") is False
            for arm in PRODUCT_ARMS
            for record in by_arm[arm]
        ),
        "labels_absent_from_context_workers": all(
            record.get("labels_opened_by_context_worker") is False
            and record.get("answer_or_answer_session_fields_accessed") is False
            for record in records
        ),
        "baseline_canonical_authority_absent": all(
            record.get("canonical_authority") is False
            for arm in (BM25_ARM, DENSE_ARM)
            for record in by_arm[arm]
        ),
        "memory_budget_exact": all(
            int(record.get("context_tokens") or 0) <= MEMORY_TOKEN_BUDGET
            for record in records
        ),
        "formation_applied_nonzero_or_pilot": (
            sum(row.get("formation_applied") is True for row in formation_rows) > 0
        ),
        "projected_500_within_resource_window": (
            target_count == 8
            or projected_500_seconds <= CONTEXT_RESOURCE_WINDOW_SECONDS
        ),
    }
    value = {
        "schema": f"{SCHEMA_VERSION}.context-seal",
        "run_id": RUN_ID,
        "capability_seal_digest": seal_digest,
        "target_count": target_count,
        "terminal_count": len(records),
        "status": "PASS" if all(gate.values()) else "FAIL",
        "records_digest": records_sha256(records),
        "source_order_sha256": canonical_sha256(target_case_ids(target_count)),
        "arms": {
            arm: {
                "terminal_count": len(by_arm[arm]),
                "succeeded": sum(
                    record.get("terminal_status") == "SUCCEEDED"
                    for record in by_arm[arm]
                ),
                "failed": sum(
                    record.get("terminal_status") != "SUCCEEDED"
                    for record in by_arm[arm]
                ),
                "context_tokens_sum": sum(
                    int(record.get("context_tokens") or 0) for record in by_arm[arm]
                ),
            }
            for arm in ARMS
        },
        "formation": {
            "eligible": sum(
                row.get("formation_eligible") is True for row in formation_rows
            ),
            "attempted": sum(
                row.get("formation_attempted") is True for row in formation_rows
            ),
            "applied": sum(
                row.get("formation_applied") is True for row in formation_rows
            ),
            "raw_fallback": sum(
                row.get("raw_fallback_taken") is True for row in formation_rows
            ),
            "formed_artifact_count": sum(
                int(row.get("formed_artifact_count") or 0) for row in formation_rows
            ),
            "hydrated_source_count": sum(
                int(row.get("hydrated_source_count") or 0) for row in formation_rows
            ),
        },
        "product_snapshot_failures": product_snapshot_failures,
        "product_runtime_failures": product_runtime_failures,
        "failure_classes": dict(sorted(failure_classes.items())),
        "wall_seconds": round(context_wall_seconds, 6),
        "projected_500_wall_seconds": round(projected_500_seconds, 6),
        "resource_window_seconds": CONTEXT_RESOURCE_WINDOW_SECONDS,
        "execution_scope": (
            "USER_LIMITED_8_CASE_PILOT" if target_count == 8 else "FORMAL_STAIRCASE"
        ),
        "runtime_terminals": {
            "bm25": dict(bm25),
            "dense": [dict(value) for value in dense],
            "product": [dict(value) for value in product],
        },
        "gate": gate,
        "labels_opened_by_context_stage": False,
        "answer_calls": 0,
        "judge_calls": 0,
    }
    atomic_json(stage_seal_path("context", target_count), value)
    return value


def run_contexts(target_count: int) -> dict[str, Any]:
    if not CAPABILITY_SEAL_PATH.is_file():
        raise MLR01R4Error("capability seal is required before contexts")
    seal_path = stage_seal_path("context", target_count)
    if seal_path.is_file():
        return require_stage_seal("context", target_count)
    stage_started = time.perf_counter()
    bm25 = run_bm25(target_count)
    dense = run_dense(target_count)
    product = run_product(target_count)
    return seal_contexts(
        target_count=target_count,
        stage_started=stage_started,
        bm25=bm25,
        dense=dense,
        product=product,
    )


__all__ = [
    "FORMED_ARM",
    "PRODUCT_SPEC",
    "RAW_ARM",
    "load_context_records",
    "run_bm25",
    "run_contexts",
    "run_dense",
    "run_product",
    "run_product_shard",
    "seal_contexts",
]
