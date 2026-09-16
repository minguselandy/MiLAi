"""Four-shard product-isomorphic Runtime executor for the GDPM B0 canary."""

from __future__ import annotations

import hashlib
import math
import os
import resource
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, cast

from evals.dg14.benchmark import (
    DEFAULT_ENV_FILE,
    DEFAULT_TOKENIZER,
    _local_token_counter,
)
from evals.dg14.contracts import (
    DG14ContractError,
    deterministic_event_id,
    deterministic_history_session_id,
    sha256_json,
)
from evals.dg15.mcp_stdio import MultiplexedStdioMcpTransport
from evals.dg15.milai_mcp_adapter import DG15MilaiMcpAdapter
from evals.dg15.runtime_session import LocalDG15RuntimeSession
from evals.gdpm.b0_canary_longmemeval import B0RuntimeCase
from evals.gdpm.b0_canary_runner import (
    EXPECTED_METRICS,
    CanaryBatchResult,
    CanaryContextCell,
)

STATEFUL_SHARDS = 4
MCP_CONCURRENCY_PER_SHARD = 1
PROJECTION_BATCH_SIZE = 64
BARRIER_TIMEOUT_MS = 120_000
MAX_RETRIEVAL_LIMIT = 12
MAX_QUERY_LATENCY_MS = 2_000
_EXPECTED_TOKENIZER_SHA256 = (
    "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42"
)
_EXPECTED_CHAT_TEMPLATE_SHA256 = (
    "e84f32a23fdda27689f868aa4a1a5621f41133e51a48d7f3efcbea2839574259"
)


class B0RuntimeExecutionError(RuntimeError):
    """The isolated Runtime execution or trace proof failed."""


def execution_plan(*, evidence_token_budget: int = 4096) -> dict[str, object]:
    """Return the physical contract frozen into the pre-execution run-lock."""

    return {
        "mode": "FOUR_ISOLATED_POSTGRES_RUNTIME_SHARDS",
        "stateful_shards": STATEFUL_SHARDS,
        "workers_per_shard": 1,
        "mcp_concurrency_per_shard": MCP_CONCURRENCY_PER_SHARD,
        "projection_batch_size": PROJECTION_BATCH_SIZE,
        "barrier_timeout_ms": BARRIER_TIMEOUT_MS,
        "max_retrieval_limit": MAX_RETRIEVAL_LIMIT,
        "max_query_latency_ms": MAX_QUERY_LATENCY_MS,
        "evidence_token_budget": evidence_token_budget,
        "memory_formation_mode": "OFF",
        "budget_invariant_context_v0_1": True,
        "progressive_context_evidence_v0_1": True,
        "automatic_retry_count": 0,
        "reader_answer_judge_calls": 0,
        "gpu_required": False,
    }


def execute_runtime_batch(
    items: tuple[tuple[str, object], ...],
    budget: int,
    *,
    run_id: str,
    runtime_root: Path,
    env_file: Path = DEFAULT_ENV_FILE,
    expected_budget: int = 4096,
) -> CanaryBatchResult:
    """Execute exactly one logical context attempt per item over four shards."""

    if budget != expected_budget:
        raise B0RuntimeExecutionError(
            f"Runtime batch requires the frozen {expected_budget} budget"
        )
    if len(items) != 24 or len({case_id for case_id, _case in items}) != 24:
        raise B0RuntimeExecutionError(
            "B0 Runtime batch requires exactly 24 unique cases"
        )
    typed_items: list[tuple[str, B0RuntimeCase]] = []
    for case_id, raw_case in items:
        if not isinstance(raw_case, B0RuntimeCase) or raw_case.case_id != case_id:
            raise B0RuntimeExecutionError("B0 Runtime case type or identity drifted")
        typed_items.append((case_id, raw_case))
    shards = tuple(
        tuple(
            item
            for ordinal, item in enumerate(typed_items)
            if ordinal % STATEFUL_SHARDS == shard
        )
        for shard in range(STATEFUL_SHARDS)
    )
    if any(len(shard) != 6 for shard in shards):
        raise B0RuntimeExecutionError("B0 Runtime shard denominator drifted")
    runtime_root.mkdir(parents=True, exist_ok=False)

    terminals: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=STATEFUL_SHARDS) as pool:
        futures = {
            pool.submit(
                _run_runtime_shard,
                run_id,
                shard,
                shard_items,
                budget,
                runtime_root,
                env_file,
            ): shard
            for shard, shard_items in enumerate(shards)
        }
        for future in as_completed(futures):
            terminals.append(future.result())
    terminals.sort(key=lambda value: int(value["shard"]))
    raw_cells = [cell for terminal in terminals for cell in terminal.pop("cells")]
    cells = tuple(_cell_from_json(value) for value in raw_cells)
    cell_ids = {cell.case_id for cell in cells}
    lifecycle_pass = all(terminal.get("status") == "PASS" for terminal in terminals)
    receipt = {
        "schema_version": "mila-gdpm-b0-runtime-execution-v0.1",
        "status": (
            "PASS"
            if lifecycle_pass and cell_ids == {item[0] for item in items}
            else "FAIL"
        ),
        "physical_plan": execution_plan(evidence_token_budget=expected_budget),
        "logical_case_count": len(items),
        "logical_attempt_count": len(cells),
        "shards": terminals,
        "formal_holdout_consumed": False,
        "reader_calls": 0,
        "answer_calls": 0,
        "judge_calls": 0,
    }
    return CanaryBatchResult(cells=cells, execution_receipt=receipt)


def run_environment_witness(*, run_id: str, output_root: Path) -> dict[str, object]:
    """Run one synthetic Runtime context and remove its temporary database."""

    from evals.dg14.contracts import DG14HistoryEvent

    if output_root.exists():
        raise B0RuntimeExecutionError("environment witness output already exists")
    case = B0RuntimeCase(
        case_id="synthetic-gdpm-b0-environment-witness",
        category="synthetic",
        question="What is the governed witness code?",
        question_at="2026-09-01T00:01:00Z",
        sessions=(),
        history_events=tuple(
            DG14HistoryEvent.from_mapping(
                {
                    "case_id": "synthetic-gdpm-b0-environment-witness",
                    "session_ordinal": ordinal,
                    "original_session_id": f"synthetic-session-{ordinal}",
                    "turn_ordinal": 0,
                    "role": "user" if ordinal % 2 == 0 else "assistant",
                    "content": (
                        f"The governed witness code candidate {ordinal} is cobalt 47. "
                        + "synthetic-padding-" * 30
                    ),
                    "observed_at": "2026-09-01T00:00:00Z",
                }
            )
            for ordinal in range(520)
        ),
    )
    terminal = _run_runtime_shard(
        run_id,
        0,
        ((case.case_id, case),),
        4096,
        output_root,
        DEFAULT_ENV_FILE,
    )
    cells = terminal.pop("cells")
    admitted = (
        cells[0].get("trace", {}).get("admitted_evidence_trace", {}) if cells else {}
    )
    compaction = admitted.get("mcp_output_compaction")
    passed = (
        terminal.get("status") == "PASS"
        and len(cells) == 1
        and cells[0].get("status") == "PASS"
        and cells[0].get("metrics") == EXPECTED_METRICS
        and isinstance(compaction, Mapping)
        and compaction.get("applied") is True
    )
    return {
        "schema_version": "mila-gdpm-b0-environment-witness-v0.1",
        "status": "PASS" if passed else "FAIL",
        "sentinel": "GDPM_B0_RUNTIME_WITNESS",
        "runtime_terminal": terminal,
        "cell": cells[0] if cells else None,
        "benchmark_cases": 0,
        "reader_answer_judge_calls": 0,
        "formal_holdout_consumed": False,
    }


def _run_runtime_shard(
    run_id: str,
    shard: int,
    items: Sequence[tuple[str, B0RuntimeCase]],
    budget: int,
    runtime_root: Path,
    env_file: Path,
) -> dict[str, Any]:
    shard_root = runtime_root / f"shard-{shard}"
    shard_root.mkdir(parents=True, exist_ok=False)
    session = LocalDG15RuntimeSession(
        output_root=shard_root,
        env_file=env_file,
        mcp_concurrency=MCP_CONCURRENCY_PER_SHARD,
        projection_batch_size=PROJECTION_BATCH_SIZE,
        inherit_source_embedding_runtime=True,
        barrier_timeout_ms=BARRIER_TIMEOUT_MS,
        memory_formation_mode="OFF",
        progressive_context_evidence=True,
        budget_invariant_context=True,
    )
    started = time.perf_counter()
    runtime: Mapping[str, Any] = {"status": "NOT_STARTED"}
    worker: Mapping[str, Any] = {"status": "NOT_STARTED"}
    projection: Mapping[str, Any] = {"status": "NOT_COLLECTED"}
    cleanup: Mapping[str, Any] = {"status": "NOT_CREATED"}
    cells: list[CanaryContextCell] = []
    shard_error: Exception | None = None
    try:
        runtime = session.start(f"{run_id}-shard-{shard}")
        counter = _local_token_counter(DEFAULT_TOKENIZER)
        for case_id, case in items:
            try:
                cells.append(
                    _execute_runtime_case(
                        session=session,
                        run_id=run_id,
                        case=case,
                        budget=budget,
                        counter=counter,
                        shard_root=shard_root,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - typed cell terminal
                cells.append(_failure_cell(case_id, exc))
    except Exception as exc:  # noqa: BLE001 - terminalize untouched shard tail
        shard_error = exc
        existing = {cell.case_id for cell in cells}
        cells.extend(
            _failure_cell(case_id, exc)
            for case_id, _case in items
            if case_id not in existing
        )
    finally:
        worker = session.worker_status()
        try:
            projection = session.projection_metrics()
        except Exception as exc:  # noqa: BLE001 - diagnostic only
            projection = {
                "status": "NOT_AVAILABLE",
                "failure_class": type(exc).__name__,
                "failure_message_sha256": hashlib.sha256(str(exc).encode()).hexdigest(),
            }
        cleanup = session.close()
    lifecycle_pass = (
        shard_error is None
        and cleanup.get("status") == "PASS"
        and isinstance(worker, Mapping)
        and worker.get("status") in {"RUNNING", "EXITED"}
        and len(cells) == len(items)
    )
    return {
        "schema_version": "mila-gdpm-b0-runtime-shard-v0.1",
        "status": "PASS" if lifecycle_pass else "FAIL",
        "shard": shard,
        "case_count": len(items),
        "process_id": os.getpid(),
        "worker_count": 1,
        "runtime": _json_safe(runtime),
        "worker_before_close": _json_safe(worker),
        "projection_metrics": _json_safe(projection),
        "runtime_cleanup": _json_safe(cleanup),
        "shard_error": type(shard_error).__name__ if shard_error else None,
        "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "cells": [_cell_to_json(cell) for cell in cells],
    }


def _execute_runtime_case(
    *,
    session: LocalDG15RuntimeSession,
    run_id: str,
    case: B0RuntimeCase,
    budget: int,
    counter: Any,
    shard_root: Path,
) -> CanaryContextCell:
    config = replace(
        session.adapter_config(),
        max_limit=MAX_RETRIEVAL_LIMIT,
        allowed_budgets=(budget,),
        project_prefix="gdpm-b0",
        barrier_timeout_ms=BARRIER_TIMEOUT_MS,
        max_latency_ms=MAX_QUERY_LATENCY_MS,
    )
    log_path = shard_root / "mcp.log"
    with log_path.open("ab") as stderr:
        transport = MultiplexedStdioMcpTransport(config.dg14_config(), stderr=stderr)
        adapter = DG15MilaiMcpAdapter(
            config,
            token_counter=counter,
            transport=transport,
            close_transport_on_cleanup=False,
        )
        try:
            adapter.reset(run_id, case.case_id)
            adapter.ingest_many(case.history_events)
            readiness = adapter.finalize()
            if readiness.get("status") != "READY":
                raise B0RuntimeExecutionError(
                    "Runtime projection barrier was not READY"
                )
            result = adapter.query(case.question, case.question_at, budget)
            metrics = _context_metrics(case, adapter, result, budget)
            receipts = adapter.export_governance_receipts()
            stats = adapter.stats()
            canonical_mutation_count = stats.claim_count + sum(
                receipt.get("canonical_changed") is not False for receipt in receipts
            )
            usage = result.usage
            admitted = dict(
                _mapping(usage.get("admitted_evidence_trace"), "admitted trace")
            )
            memory_context = _mapping(
                result.raw_resolve.get("memory_context"), "Runtime MemoryContext"
            )
            admitted.update(
                {
                    "runtime_status": result.status,
                    "runtime_compile_trace": _json_safe(
                        memory_context.get("compile_trace")
                    ),
                    "runtime_windows": _json_safe(memory_context.get("windows")),
                    "mcp_output_compaction": _json_safe(
                        result.raw_resolve.get("mcp_output_compaction")
                    ),
                    "governance_receipts": _json_safe(receipts),
                    "declared_reader_memory_tokens": result.declared_tokens,
                    "query_latency_ms": result.latency_ms,
                    "readiness_target_watermark": readiness.get("target_watermark"),
                }
            )
            return CanaryContextCell(
                case_id=case.case_id,
                status="PASS" if metrics == EXPECTED_METRICS else "FAILED",
                metrics=metrics,
                trace={
                    "raw_retrieval_trace": _json_safe(usage.get("raw_retrieval_trace")),
                    "admitted_evidence_trace": admitted,
                    "reader_visible_trace": _json_safe(
                        usage.get("reader_visible_trace")
                    ),
                    "reader_context": result.context,
                },
                canonical_mutation_count=canonical_mutation_count,
                failure_class=(
                    None if metrics == EXPECTED_METRICS else "PROTOCOL_IMPLEMENTATION"
                ),
                semantic_abstention=result.status in {"ABSENT", "ABSTAINED"},
            )
        finally:
            transport.close()


def _context_metrics(
    case: B0RuntimeCase,
    adapter: DG15MilaiMcpAdapter,
    result: Any,
    budget: int,
) -> dict[str, float | int]:
    usage = result.usage
    raw = usage.get("raw_retrieval_trace")
    admitted = _mapping(usage.get("admitted_evidence_trace"), "admitted trace")
    visible = _mapping(usage.get("reader_visible_trace"), "Reader-visible trace")
    memory_context = _mapping(
        result.raw_resolve.get("memory_context"), "Runtime MemoryContext"
    )
    compile_trace = _mapping(memory_context.get("compile_trace"), "compile trace")
    receipts = adapter.export_governance_receipts()
    events = {event.event_id: event for event in case.history_events}
    receipt_events = {str(receipt.get("event_id")): receipt for receipt in receipts}
    expected_event_ids = {
        deterministic_event_id(
            event.case_id,
            event.session_ordinal,
            event.original_session_id,
            event.turn_ordinal,
        )
        for event in case.history_events
    }
    evidence_sessions: dict[str, str] = {}
    evidence_events: dict[str, Any] = {}
    evidence_turn_ids: dict[str, str] = {}
    evidence_governance_digests: dict[str, str] = {}
    source_sessions: dict[str, str] = {}
    source_identity_exact = set(events) == expected_event_ids == set(receipt_events)
    evidence_ids: set[str] = set()
    expected_subject = adapter._case_subject()
    for event_id, receipt in receipt_events.items():
        event = events.get(event_id)
        evidence_id = receipt.get("evidence_id")
        source_ref = receipt.get("source_ref")
        if (
            event is None
            or not isinstance(evidence_id, str)
            or not isinstance(source_ref, str)
            or source_ref != adapter._event_source_ref(event)
            or evidence_id in evidence_ids
        ):
            source_identity_exact = False
            continue
        evidence_ids.add(evidence_id)
        session_id = deterministic_history_session_id(
            event.case_id, event.session_ordinal, event.original_session_id
        )
        expected_turn_id = f"{session_id}:turn:{event.turn_ordinal}"
        capture_request = receipt.get("capture_request")
        source_event_identity = receipt.get("source_event_identity")
        confirmation = receipt.get("confirmation_summary")
        source_context = (
            capture_request.get("source_context")
            if isinstance(capture_request, Mapping)
            else None
        )
        if (
            not isinstance(capture_request, Mapping)
            or not isinstance(source_event_identity, Mapping)
            or not isinstance(confirmation, Mapping)
            or not isinstance(source_context, Mapping)
            or capture_request.get("source_ref") != source_ref
            or capture_request.get("subject_id") != expected_subject
            or capture_request.get("confirmation") != "CAPTURE"
            or source_event_identity.get("case_id") != event.case_id
            or source_event_identity.get("event_id") != event.event_id
            or source_event_identity.get("original_session_id")
            != event.original_session_id
            or not _is_exact_int(
                source_event_identity.get("session_ordinal"), event.session_ordinal
            )
            or not _is_exact_int(
                source_event_identity.get("turn_ordinal"), event.turn_ordinal
            )
            or source_context.get("session_id") != session_id
            or source_context.get("turn_id") != expected_turn_id
            or not _is_exact_int(source_context.get("turn_ordinal"), event.turn_ordinal)
            or confirmation.get("source_ref") != source_ref
            or confirmation.get("subject_id") != expected_subject
            or confirmation.get("source_type") != capture_request.get("source_type")
            or confirmation.get("speaker") != capture_request.get("speaker")
            or confirmation.get("structured_source_context") is not True
            or confirmation.get("permission_purpose")
            != capture_request.get("permission_purpose")
            or confirmation.get("retention_state")
            != capture_request.get("retention_state")
            or confirmation.get("data_classification")
            != capture_request.get("data_classification")
            or not isinstance(confirmation.get("runtime_request_id"), str)
            or not confirmation.get("runtime_request_id")
        ):
            source_identity_exact = False
        evidence_sessions[evidence_id] = session_id
        evidence_events[evidence_id] = event
        evidence_turn_ids[evidence_id] = expected_turn_id
        evidence_governance_digests[evidence_id] = sha256_json(
            {
                "source_event_identity": source_event_identity,
                "capture_request": capture_request,
                "confirmation_summary": confirmation,
            }
        )
        source_sessions[source_ref] = session_id
    raw_subjects: set[str] = set()
    raw_evidence_ids: set[str] = set()
    raw_source_refs: set[str] = set()
    if not isinstance(raw, (list, tuple)):
        source_identity_exact = False
        raw = []
    if not raw:
        source_identity_exact = False
    for ordinal, row in enumerate(raw, start=1):
        identity = row.get("evidence_identity") if isinstance(row, Mapping) else None
        if not isinstance(identity, Mapping):
            source_identity_exact = False
            continue
        evidence_id = identity.get("evidence_id")
        source_ref = identity.get("source_ref")
        expected_session = evidence_sessions.get(str(evidence_id))
        event = evidence_events.get(str(evidence_id))
        raw_score = row.get("raw_score") if isinstance(row, Mapping) else None
        if (
            expected_session is None
            or event is None
            or row.get("channel") != "RUNTIME_EVIDENCE_RESOLVE"
            or not _is_exact_int(row.get("channel_rank"), ordinal)
            or (
                raw_score is not None
                and (
                    isinstance(raw_score, bool)
                    or not isinstance(raw_score, (int, float))
                    or not math.isfinite(float(raw_score))
                )
            )
            or source_sessions.get(str(source_ref)) != expected_session
            or identity.get("source_session_id") != expected_session
            or identity.get("original_session_id") != event.original_session_id
            or not _is_exact_int(identity.get("session_ordinal"), event.session_ordinal)
            or identity.get("turn_id") != evidence_turn_ids.get(str(evidence_id))
            or row.get("capture_governance_sha256")
            != evidence_governance_digests.get(str(evidence_id))
            or str(evidence_id) in raw_evidence_ids
            or str(source_ref) in raw_source_refs
        ):
            source_identity_exact = False
        raw_evidence_ids.add(str(evidence_id))
        raw_source_refs.add(str(source_ref))
        subject_id = identity.get("subject_id")
        if isinstance(subject_id, str):
            raw_subjects.add(subject_id)
    if raw_subjects != {expected_subject} or raw_subjects.intersection(
        evidence_sessions.values()
    ):
        source_identity_exact = False

    cross_session_expansions = 0
    windows = memory_context.get("windows")
    if not isinstance(windows, list):
        windows = []
        cross_session_expansions += 1
    for window in windows:
        if not isinstance(window, Mapping):
            cross_session_expansions += 1
            continue
        window_session_id = window.get("session_id")
        window_evidence = window.get("evidence_ids")
        if not isinstance(window_evidence, list):
            cross_session_expansions += 1
            continue
        mapped = {evidence_sessions.get(str(value)) for value in window_evidence}
        if mapped != {window_session_id}:
            cross_session_expansions += 1
        expansions = window.get("expansions")
        if isinstance(expansions, list):
            for expansion in expansions:
                if not isinstance(expansion, Mapping):
                    cross_session_expansions += 1
                    continue
                expanded = expansion.get("expanded_evidence_ids")
                linked = [expansion.get("source_evidence_id")]
                if isinstance(expanded, list):
                    linked.extend(expanded)
                if {evidence_sessions.get(str(value)) for value in linked} != {
                    window_session_id
                }:
                    cross_session_expansions += 1

    context = result.context
    parts = visible.get("serialization_parts")
    replayed = "\n\n".join(parts) if isinstance(parts, list) else None
    replay_exact = (
        replayed == context
        and visible.get("serialization_replay_sha256")
        == hashlib.sha256(context.encode()).hexdigest()
        and visible.get("reader_context_sha256")
        == hashlib.sha256(context.encode()).hexdigest()
    )
    offsets_exact = replay_exact
    encoded = context.encode()
    rendered_units = visible.get("rendered_units")
    if not isinstance(rendered_units, list):
        offsets_exact = False
        rendered_units = []
    for unit in rendered_units:
        if not isinstance(unit, Mapping):
            offsets_exact = False
            continue
        byte_offset = unit.get("serialized_utf8_byte_offset")
        char_offset = unit.get("serialized_char_offset")
        if not isinstance(byte_offset, Mapping) or not isinstance(char_offset, Mapping):
            offsets_exact = False
            continue
        try:
            byte_start = _exact_nonnegative_int(byte_offset.get("start"), "byte start")
            byte_end = _exact_nonnegative_int(byte_offset.get("end"), "byte end")
            char_start = _exact_nonnegative_int(char_offset.get("start"), "char start")
            char_end = _exact_nonnegative_int(char_offset.get("end"), "char end")
            prompt_start = _exact_nonnegative_int(
                unit.get("reader_prompt_token_start"), "Reader prompt token start"
            )
            prompt_end = _exact_nonnegative_int(
                unit.get("reader_prompt_token_end"), "Reader prompt token end"
            )
            byte_value = encoded[byte_start:byte_end]
            char_value = context[char_start:char_end]
            offsets_exact = offsets_exact and byte_value.decode() == char_value
            offsets_exact = offsets_exact and hashlib.sha256(
                byte_value
            ).hexdigest() == unit.get("serialized_unit_sha256")
            offsets_exact = offsets_exact and prompt_end > prompt_start
        except (KeyError, TypeError, ValueError, UnicodeDecodeError):
            offsets_exact = False
    receipt = result.raw_resolve.get("context_receipt")
    selected_ids = memory_context.get("selected_evidence_ids")
    if isinstance(receipt, Mapping):
        receipt_mapping = receipt.get("receipt_mapping")
        receipt_ids = receipt.get("source_evidence_ids")
        if (
            not isinstance(receipt_mapping, list)
            or not isinstance(receipt_ids, list)
            or not isinstance(selected_ids, list)
            or len(receipt_mapping) != len(rendered_units)
        ):
            offsets_exact = False
        else:
            mapping_by_alias = {
                str(item.get("alias")): item
                for item in receipt_mapping
                if isinstance(item, Mapping)
                and isinstance(item.get("alias"), str)
                and item.get("alias")
            }
            rendered_by_alias = {
                str(item.get("alias")): item
                for item in rendered_units
                if isinstance(item, Mapping)
                and isinstance(item.get("alias"), str)
                and item.get("alias")
            }
            offsets_exact = offsets_exact and (
                len(mapping_by_alias) == len(receipt_mapping)
                and len(rendered_by_alias) == len(rendered_units)
                and set(mapping_by_alias) == set(rendered_by_alias)
                and {str(value) for value in receipt_ids}
                == {str(value) for value in selected_ids}
            )
            mapped_source_refs = {
                str(value)
                for mapping in receipt_mapping
                if isinstance(mapping, Mapping)
                and isinstance(mapping.get("source_turn_refs"), list)
                for value in mapping["source_turn_refs"]
            }
            selected_source_refs = memory_context.get("selected_source_turn_refs")
            offsets_exact = offsets_exact and (
                isinstance(selected_source_refs, list)
                and mapped_source_refs == {str(value) for value in selected_source_refs}
            )
            for alias, mapping in mapping_by_alias.items():
                rendered = rendered_by_alias.get(alias)
                if rendered is None:
                    offsets_exact = False
                    continue
                for key in ("evidence_ids", "source_turn_refs"):
                    expected_values = mapping.get(key)
                    actual_values = rendered.get(key)
                    if (
                        not isinstance(expected_values, list)
                        or not isinstance(actual_values, list)
                        or expected_values != actual_values
                    ):
                        offsets_exact = False
    elif selected_ids or rendered_units:
        offsets_exact = False
    reader_call_count = _exact_nonnegative_int(
        visible.get("reader_call_count"), "Reader call count"
    )
    offsets_exact = (
        offsets_exact
        and visible.get("tokenizer_sha256") == _EXPECTED_TOKENIZER_SHA256
        and visible.get("chat_template_sha256") == _EXPECTED_CHAT_TEMPLATE_SHA256
        and reader_call_count == 0
        and isinstance(result.declared_tokens, int)
        and not isinstance(result.declared_tokens, bool)
        and result.declared_tokens >= 0
        and result.declared_tokens <= budget
    )
    atomic = _exact_nonnegative_int(
        admitted.get("atomic_unit_truncation_count"),
        "admitted atomic-unit truncation count",
    ) + _exact_nonnegative_int(
        compile_trace.get("atomic_unit_truncation_count"),
        "compile atomic-unit truncation count",
    )
    long_splits = _exact_nonnegative_int(
        compile_trace.get("long_turn_split_count"), "long-turn split count"
    ) + sum(
        int(window.get("truncated") is True)
        for window in windows
        if isinstance(window, Mapping)
    )
    rank_violations = _exact_nonnegative_int(
        compile_trace.get("rank_first_prefix_violation_count"),
        "rank-first prefix violation count",
    )
    if compile_trace.get("whole_unit_admission") is not True:
        atomic += 1
    return {
        "SessionIdentityIntegrity": float(source_identity_exact),
        "CrossSourceSessionAdjacencyExpansion": cross_session_expansions,
        "ReaderVisibleTraceExactness": float(offsets_exact),
        "ContextSerializationReplayEquivalence": float(replay_exact),
        "SystemFailureAsSemanticAbstention": 0,
        "ReaderCallsDuringContextPreflight": reader_call_count,
        "AtomicUnitTruncationCount": atomic,
        "LongTurnSplitCount": long_splits,
        "RankFirstPrefixViolationCount": rank_violations,
    }


def _failure_cell(case_id: str, error: Exception) -> CanaryContextCell:
    failure_class = (
        "INFRASTRUCTURE"
        if isinstance(error, (ConnectionError, OSError, TimeoutError))
        else "PROTOCOL_IMPLEMENTATION"
    )
    metrics = {
        name: 0 if expected == 1.0 else expected
        for name, expected in EXPECTED_METRICS.items()
    }
    return CanaryContextCell(
        case_id=case_id,
        status="FAILED",
        metrics=metrics,
        trace={
            "raw_retrieval_trace": {
                "failure_class": failure_class,
                "failure_type": type(error).__name__,
                "message": str(error)[:500],
            },
            "admitted_evidence_trace": {},
            "reader_visible_trace": {"reader_call_count": 0},
            "reader_context": "",
        },
        failure_class=failure_class,
        semantic_abstention=False,
    )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DG14ContractError(f"{label} is absent")
    return value


def _exact_nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DG14ContractError(f"{label} is not an exact nonnegative integer")
    return value


def _is_exact_int(value: object, expected: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


def _cell_to_json(cell: CanaryContextCell) -> dict[str, Any]:
    return cast(dict[str, Any], _json_safe(asdict(cell)))


def _cell_from_json(value: Mapping[str, Any]) -> CanaryContextCell:
    return CanaryContextCell(
        case_id=str(value["case_id"]),
        status=str(value["status"]),
        metrics=dict(value["metrics"]),
        trace=dict(value["trace"]),
        reader_calls=int(value.get("reader_calls", 0)),
        answer_calls=int(value.get("answer_calls", 0)),
        judge_calls=int(value.get("judge_calls", 0)),
        canonical_mutation_count=int(value.get("canonical_mutation_count", 0)),
        failure_class=(
            str(value["failure_class"])
            if value.get("failure_class") is not None
            else None
        ),
        semantic_abstention=bool(value.get("semantic_abstention", False)),
    )


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


__all__ = [
    "B0RuntimeExecutionError",
    "execute_runtime_batch",
    "execution_plan",
    "run_environment_witness",
]
