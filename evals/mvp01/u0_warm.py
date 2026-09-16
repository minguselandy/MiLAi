"""Real MCP/Runtime executor for the MVP-01 U0 100-request warm soak."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
import platform
import resource
import signal
import sys
import threading
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from evals.dg14.benchmark import (
    DEFAULT_CHAT_TEMPLATE,
    DEFAULT_ENV_FILE,
    DEFAULT_TOKENIZER,
    EXPECTED_CHAT_TEMPLATE_SHA256,
    EXPECTED_TOKENIZER_SHA256,
    _local_token_counter,
)
from evals.dg14.contracts import (
    DG14ContractError,
    DG14HistoryEvent,
    deterministic_history_session_id,
    deterministic_project_id,
    sha256_json,
)
from evals.dg14.reader_token_accounting import (
    FrozenReaderTokenAccountingError,
    frozen_reader_token_counter,
)
from evals.dg15.contracts import DG15AdapterConfig
from evals.dg15.mcp_stdio import MultiplexedStdioMcpTransport
from evals.dg15.milai_mcp_adapter import DG15MilaiMcpAdapter
from evals.dg15.runtime_session import LocalDG15RuntimeSession
from evals.gdpm.b0_canary_longmemeval import B0RuntimeCase
from evals.gdpm.b0_canary_runner import EXPECTED_METRICS
from evals.gdpm.b0_canary_runtime import _context_metrics
from evals.mvp01.u0_warm_contract import (
    AUTHORIZED_RUN_ID,
    AUTHORIZED_RUN_LOCK,
    EVIDENCE_TOKEN_BUDGET,
    REQUEST_COUNT,
    SCOPE_IDENTITY,
    WarmAuthorityReceipt,
    assert_mvp01_u0_warm_authorized,
    assert_previous_u0_gate,
)

MAX_RETRIEVAL_LIMIT = 12
MAX_QUERY_LATENCY_MS = 2_000
WARM_MEMORY_CONTROL_P95_MS = 500.0
READ_AFTER_WRITE_MAX_MS = 60_000.0
READ_AFTER_WRITE_TARGET_MS = 5_000.0
AUTOMATIC_RETRY_COUNT = 0
FIXTURE_CASE_ID = "mvp01-u0-warm-synthetic-v1"
FIXTURE_EVENT_COUNT = 20
EXPECTED_PROJECTIONS = frozenset({"evidence", "fts", "vector", "purge"})
EXPECTED_PROJECTION_DELIVERIES = frozenset(
    {
        ("evidence", "EVIDENCE_INGESTED", "APPLY", "PROJECTED"),
        (
            "evidence",
            "EVIDENCE_REVOKED",
            "ACK_NOT_APPLICABLE",
            "EXPLICIT_SKIP",
        ),
        (
            "evidence",
            "PURGE_EVIDENCE_DERIVATIVES",
            "APPLY",
            "PURGED",
        ),
        ("fts", "EVIDENCE_INGESTED", "ACK_NOT_APPLICABLE", "EXPLICIT_SKIP"),
        ("fts", "EVIDENCE_REVOKED", "ACK_NOT_APPLICABLE", "EXPLICIT_SKIP"),
        ("fts", "PURGE_EVIDENCE_DERIVATIVES", "APPLY", "PURGED"),
        (
            "vector",
            "EVIDENCE_INGESTED",
            "ACK_NOT_APPLICABLE",
            "EXPLICIT_SKIP",
        ),
        (
            "vector",
            "EVIDENCE_REVOKED",
            "ACK_NOT_APPLICABLE",
            "EXPLICIT_SKIP",
        ),
        ("vector", "PURGE_EVIDENCE_DERIVATIVES", "APPLY", "PURGED"),
        (
            "purge",
            "EVIDENCE_INGESTED",
            "ACK_NOT_APPLICABLE",
            "EXPLICIT_SKIP",
        ),
        (
            "purge",
            "EVIDENCE_REVOKED",
            "ACK_NOT_APPLICABLE",
            "EXPLICIT_SKIP",
        ),
        (
            "purge",
            "PURGE_EVIDENCE_DERIVATIVES",
            "APPLY",
            "PURGED_DERIVATIVES",
        ),
    }
)
EXPECTED_PROJECTION_LOGICAL_ITEMS = FIXTURE_EVENT_COUNT
EXPECTED_PROJECTION_TERMINAL_WATERMARK = FIXTURE_EVENT_COUNT * 3
PASS_STATUS = "PASS_MVP01_U0_100_REQUEST_WARM_RELIABILITY_SOAK"
FAIL_STATUS = "FAIL_MVP01_U0_100_REQUEST_WARM_RELIABILITY_SOAK_REPAIR_REQUIRED"
CHECKPOINT_SCHEMA = "mila-mvp01-u0-warm-checkpoint-v0.3"
EVIDENCE_ARCHIVE_SCHEMA = "mila-mvp01-u0-warm-request-evidence-v0.5"


class U0WarmExecutionError(RuntimeError):
    """The warm composition or its sealed contract failed."""


class U0WarmInterruption(BaseException):
    """A process signal requested graceful, fail-closed warm-run sealing."""


class _CaptureContractTransport:
    """Resource-free transport stub used only for pre-wire payload construction."""

    def open_case(self, scope: Mapping[str, object]) -> None:
        if not scope.get("project_ids"):
            raise U0WarmExecutionError("capture contract scope lacks project identity")

    def close(self) -> None:
        return None


def build_synthetic_fixture() -> B0RuntimeCase:
    """Return the fixed label-free, multi-session warm fixture."""

    sessions = (
        (
            "editor",
            "Please remember: my preferred editor is Helix with Solarized Dark.",
            "Recorded: Helix and Solarized Dark are your editor preferences.",
        ),
        (
            "allergy",
            "请记住：我的过敏原是花生，外出就餐要避开花生酱。",
            "已记录花生过敏及需要避开花生酱。",
        ),
        (
            "atlas",
            "Project Atlas has its deployment window on Friday at 09:30 Asia/Shanghai.",
            "Recorded the Atlas Friday 09:30 Shanghai deployment window.",
        ),
        (
            "bicycle",
            "I corrected my bicycle lock reminder word from cedar to maple.",
            "The current bicycle lock reminder word is maple, superseding cedar.",
        ),
        (
            "travel",
            "For the Suzhou trip, I booked the 08:12 train from Shanghai Hongqiao.",
            "Recorded the Suzhou train at 08:12 from Shanghai Hongqiao.",
        ),
        (
            "coffee",
            "My usual coffee order is a small oat flat white with no syrup.",
            "Recorded: small oat flat white, no syrup.",
        ),
        (
            "contact",
            "My synthetic emergency contact is Rowan at extension 204.",
            "Recorded Rowan and synthetic extension 204 as the emergency contact.",
        ),
        (
            "pet",
            "The synthetic pet care note says Momo takes the blue tablet after dinner.",
            "Recorded Momo's blue tablet schedule after dinner.",
        ),
        (
            "billing",
            "Send the synthetic Acme invoice to the finance-blue folder before Tuesday.",
            "Recorded the Acme invoice destination finance-blue and Tuesday deadline.",
        ),
        (
            "book-club",
            "The book club chose The Left Hand of Darkness for the September meeting.",
            "Recorded the September book-club choice, The Left Hand of Darkness.",
        ),
    )
    base = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    events = tuple(
        DG14HistoryEvent.from_mapping(
            {
                "case_id": FIXTURE_CASE_ID,
                "session_ordinal": session_ordinal,
                "original_session_id": f"warm-session-{session_name}",
                "turn_ordinal": turn_ordinal,
                "role": "user" if turn_ordinal == 0 else "assistant",
                "content": content,
                "observed_at": (
                    base + timedelta(minutes=session_ordinal, seconds=turn_ordinal)
                )
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )
        for session_ordinal, (session_name, user_text, assistant_text) in enumerate(
            sessions
        )
        for turn_ordinal, content in enumerate((user_text, assistant_text))
    )
    return B0RuntimeCase(
        case_id=FIXTURE_CASE_ID,
        category="synthetic-warm-reliability",
        question="Which synthetic memory is requested?",
        question_at="2026-09-01T01:00:00Z",
        sessions=(),
        history_events=events,
    )


def build_request_schedule() -> tuple[dict[str, str], ...]:
    """Return exactly 100 deterministic request identities and query classes."""

    templates = (
        ("editor", "Which editor and theme do I prefer: Helix or something else?"),
        ("allergy", "我的过敏原是什么，是否要避开花生酱？"),
        ("atlas", "When is the Project Atlas deployment window in Shanghai time?"),
        ("bicycle", "What is the current bicycle lock reminder word after correction?"),
        ("travel", "Which Suzhou train did I book from Shanghai Hongqiao?"),
        ("coffee", "What is my usual coffee order, including milk and syrup?"),
        ("contact", "Who is my synthetic emergency contact and extension?"),
        ("pet", "When does Momo take the blue tablet?"),
        ("billing", "Where should the synthetic Acme invoice go, and by when?"),
        ("book-club", "Which book was chosen for the September book club?"),
    )
    return tuple(
        {
            "request_id": f"warm-request-{ordinal:03d}",
            "query_class": templates[(ordinal - 1) % len(templates)][0],
            "question": templates[(ordinal - 1) % len(templates)][1],
            "question_at": "2026-09-01T01:00:00Z",
            "expected_source_ref_prefix": (
                f"mvp01-warm://case/{FIXTURE_CASE_ID}/session/"
                f"{(ordinal - 1) % len(templates)}/warm-session-"
                f"{templates[(ordinal - 1) % len(templates)][0]}/turn/"
            ),
        }
        for ordinal in range(1, REQUEST_COUNT + 1)
    )


def nearest_rank_percentile(values: Sequence[float], percentile: float) -> float | None:
    """Return a frozen nearest-rank percentile for positive finite timings."""

    if not 0.0 < percentile <= 1.0:
        raise ValueError("percentile must be in (0, 1]")
    cleaned: list[float] = []
    for raw_value in values:
        value = float(raw_value)
        if isinstance(raw_value, bool) or not math.isfinite(value) or value < 0.0:
            raise ValueError("percentile values must be finite and non-negative")
        cleaned.append(value)
    cleaned.sort()
    if not cleaned:
        return None
    return cleaned[max(0, math.ceil(percentile * len(cleaned)) - 1)]


def run_u0_warm_soak(
    *,
    run_id: str,
    output_root: Path,
    project_root: Path,
    master_path: Path,
    goal_path: Path,
    env_file: Path = DEFAULT_ENV_FILE,
) -> dict[str, object]:
    """Execute and seal the exactly authorized real 100-request warm soak."""

    authority = assert_mvp01_u0_warm_authorized(
        master_path=master_path,
        goal_path=goal_path,
    )
    predecessor = assert_previous_u0_gate(project_root)
    expected_output_root = (project_root / AUTHORIZED_RUN_LOCK).parent
    if run_id != AUTHORIZED_RUN_ID:
        raise U0WarmExecutionError(
            f"warm run id drifted: expected {AUTHORIZED_RUN_ID}, got {run_id}"
        )
    if output_root.resolve() != expected_output_root.resolve():
        raise U0WarmExecutionError(
            f"warm output root drifted: expected {expected_output_root}, got {output_root}"
        )
    fixture = build_synthetic_fixture()
    schedule = build_request_schedule()
    if (
        len(schedule) != REQUEST_COUNT
        or len({row["request_id"] for row in schedule}) != REQUEST_COUNT
    ):
        raise U0WarmExecutionError("warm request denominator or identity drifted")
    current_run_lock = _build_run_lock(
        run_id=run_id,
        authority=authority,
        predecessor=predecessor,
        fixture=fixture,
        schedule=schedule,
        project_root=project_root,
        env_file=env_file,
    )
    run_lock_path = output_root / "run-lock.json"
    checkpoint_path = output_root / "checkpoint/state.json"
    output_preexisted = output_root.exists()
    if output_preexisted:
        if (output_root / "terminal.json").exists():
            raise U0WarmExecutionError(
                "warm run is already terminal and cannot be replayed"
            )
        run_lock = _read_json_object(run_lock_path, "warm run lock")
        _assert_run_lock_current(run_lock, current_run_lock)
        run_lock_sha256 = _sha256_file(run_lock_path)
        checkpoint = _read_json_object(checkpoint_path, "warm checkpoint")
        _validate_checkpoint(
            checkpoint,
            run_id=run_id,
            run_lock_sha256=run_lock_sha256,
            schedule=schedule,
        )
    else:
        run_lock = current_run_lock
        checkpoint, run_lock_sha256 = _initialize_warm_output(
            output_root=output_root,
            run_lock=run_lock,
            run_id=run_id,
            schedule=schedule,
        )
    requests = [
        dict(row)
        for row in _require_sequence_of_mappings(
            checkpoint.get("requests"), "checkpoint requests"
        )
    ]
    runtime_attempts = [
        dict(row)
        for row in _require_sequence_of_mappings(
            checkpoint.get("runtime_attempts"), "checkpoint runtime attempts"
        )
    ]
    runtime_attempt_count = _require_nonnegative_int(
        checkpoint.get("runtime_attempt_count"), "runtime attempt count"
    )
    interruption_count = _require_nonnegative_int(
        checkpoint.get("interruption_count"), "interruption count"
    )
    artifact_seal_resumed, resumed_after_crash = _checkpoint_resume_flags(
        output_preexisted=output_preexisted,
        phase=checkpoint.get("phase"),
        request_count=len(requests),
        runtime_attempt_count=runtime_attempt_count,
    )
    stale_in_flight = checkpoint.get("in_flight")
    recovered_interruption = False
    if isinstance(stale_in_flight, Mapping):
        ordinal = _require_positive_int(
            stale_in_flight.get("ordinal"), "in-flight ordinal"
        )
        request = schedule[ordinal - 1]
        requests.append(
            _uncertain_request(
                ordinal,
                request,
                U0WarmExecutionError(
                    "prior process ended with an in-flight request; request was not replayed"
                ),
                logical_mcp_call_delta=None,
                resolve_calls=(),
                elapsed_ms=None,
            )
        )
        interruption_count += 1
        recovered_interruption = True
        _mark_open_runtime_attempt_crashed(runtime_attempts)
        checkpoint["requests"] = requests
        checkpoint["in_flight"] = None
        checkpoint["interruption_count"] = interruption_count
        checkpoint["runtime_attempts"] = runtime_attempts
        checkpoint["phase"] = "RECOVERED_UNCERTAIN_REQUEST"
        _atomic_json(checkpoint_path, checkpoint)

    if checkpoint.get("phase") == "LIFECYCLE_TERMINAL":
        sealed_lifecycle = _require_mapping(
            checkpoint.get("lifecycle"), "checkpoint lifecycle"
        )
        return _seal_warm_artifacts(
            output_root=output_root,
            run_id=run_id,
            run_lock=run_lock,
            run_lock_sha256=run_lock_sha256,
            checkpoint_path=checkpoint_path,
            fixture=fixture,
            requests=requests,
            runtime_attempts=runtime_attempts,
            runtime_attempt_count=runtime_attempt_count,
            interruption_count=interruption_count,
            resumed_after_crash=resumed_after_crash,
            artifact_seal_resumed=artifact_seal_resumed,
            lifecycle=sealed_lifecycle,
        )

    # The authority freezes one fresh composition. A later process cannot
    # reconstruct the ephemeral role credentials of an earlier composition,
    # so an incomplete prior attempt is terminal failure evidence rather than
    # permission to create a second database/API/worker composition.
    if runtime_attempt_count > 0:
        if not recovered_interruption:
            interruption_count += 1
            _mark_open_runtime_attempt_crashed(runtime_attempts)
        prior_error = U0WarmExecutionError(
            "an earlier Runtime attempt did not seal its lifecycle; a second "
            "composition is prohibited by the warm authority"
        )
        for ordinal in range(len(requests) + 1, REQUEST_COUNT + 1):
            requests.append(
                _failure_request(
                    ordinal,
                    schedule[ordinal - 1],
                    prior_error,
                    attempt_count=0,
                    terminal_type="NOT_ATTEMPTED_PRIOR_RUNTIME_CRASH",
                )
            )
        final_identity_check = _final_identity_check(
            run_id=run_id,
            run_lock=run_lock,
            fixture=fixture,
            schedule=schedule,
            project_root=project_root,
            master_path=master_path,
            goal_path=goal_path,
            env_file=env_file,
        )
        recovery_lifecycle = {
            "runtime": {"status": "INTERRUPTED_OR_CRASHED"},
            "readiness": {"status": "UNKNOWN_AFTER_PROCESS_LOSS"},
            "namespace_cleanup": {
                "status": "NOT_RECOVERABLE_WITHOUT_EPHEMERAL_CREDENTIALS",
                "cleanup_terminal": False,
            },
            "worker_before_close": {"status": "UNKNOWN_AFTER_PROCESS_LOSS"},
            "projection_metrics": {"status": "UNKNOWN_AFTER_PROCESS_LOSS"},
            "runtime_cleanup": {
                "status": "NOT_RECOVERABLE_WITHOUT_EPHEMERAL_CREDENTIALS"
            },
            "transport_cleanup": {"status": "UNKNOWN_AFTER_PROCESS_LOSS"},
            "log_cleanup": {"status": "UNKNOWN_AFTER_PROCESS_LOSS"},
            "shared_error": _error_receipt(prior_error),
            "cleanup_error": None,
            "ingest_ms": None,
            "read_after_write_searchable_ms": None,
            "final_identity_check": final_identity_check,
            "wall_ms": 0.0,
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
        checkpoint.update(
            {
                "schema_version": CHECKPOINT_SCHEMA,
                "phase": "LIFECYCLE_TERMINAL",
                "requests": requests,
                "in_flight": None,
                "runtime_attempt_count": runtime_attempt_count,
                "runtime_attempts": runtime_attempts,
                "interruption_count": interruption_count,
                "lifecycle": recovery_lifecycle,
                "sealed_at": _now(),
            }
        )
        _atomic_json(checkpoint_path, checkpoint)
        return _seal_warm_artifacts(
            output_root=output_root,
            run_id=run_id,
            run_lock=run_lock,
            run_lock_sha256=run_lock_sha256,
            checkpoint_path=checkpoint_path,
            fixture=fixture,
            requests=requests,
            runtime_attempts=runtime_attempts,
            runtime_attempt_count=runtime_attempt_count,
            interruption_count=interruption_count,
            resumed_after_crash=True,
            artifact_seal_resumed=False,
            lifecycle=recovery_lifecycle,
        )

    orphan_preflight = _assert_no_owned_orphan(
        project_root=project_root,
        run_id=run_id,
    )
    checkpoint["orphan_preflight"] = orphan_preflight
    checkpoint["phase"] = "ORPHAN_PREFLIGHT_PASSED"
    _atomic_json(checkpoint_path, checkpoint)

    started = time.perf_counter()
    runtime: Mapping[str, Any] = {"status": "NOT_STARTED"}
    readiness: Mapping[str, object] = {"status": "NOT_STARTED"}
    cleanup: Mapping[str, object] = {"status": "NOT_SUBMITTED"}
    worker_before_close: Mapping[str, object] = {"status": "NOT_STARTED"}
    projection: Mapping[str, Any] = {"status": "NOT_COLLECTED"}
    runtime_cleanup: Mapping[str, Any] = {"status": "NOT_CREATED"}
    transport_cleanup: Mapping[str, object] = {"status": "NOT_STARTED"}
    log_cleanup: Mapping[str, object] = {"status": "NOT_STARTED"}
    adapter: DG15MilaiMcpAdapter | None = None
    transport: MultiplexedStdioMcpTransport | None = None
    mcp_log: Any | None = None
    adapter_active = False
    shared_error: BaseException | None = None
    ingest_ms: float | None = None
    read_after_write_ms: float | None = None
    cleanup_error: BaseException | None = None
    capture_outcome_summary: Mapping[str, object] = {"status": "NOT_CREATED"}
    runtime_artifacts: Mapping[str, object] = {"status": "NOT_CREATED"}
    session: LocalDG15RuntimeSession | None = None
    signal_guard = _SignalGuard()
    signal_guard.install()
    runtime_attempt_count += 1
    runtime_root = output_root / "runtime" / f"attempt-{runtime_attempt_count:03d}"
    runtime_attempt = {
        "attempt": runtime_attempt_count,
        "started_at": _now(),
        "status": "STARTING",
        "runtime_root": str(runtime_root),
    }
    runtime_attempts.append(runtime_attempt)
    checkpoint["runtime_attempt_count"] = runtime_attempt_count
    checkpoint["runtime_attempts"] = runtime_attempts
    checkpoint["phase"] = "RUNTIME_STARTING"
    _atomic_json(checkpoint_path, checkpoint)
    try:
        session = LocalDG15RuntimeSession(
            output_root=runtime_root,
            env_file=env_file,
            project_root=project_root,
            mcp_concurrency=4,
            projection_batch_size=64,
            inherit_source_embedding_runtime=True,
            barrier_timeout_ms=120_000,
            data_mode="SYNTHETIC_ONLY",
            memory_formation_mode="OFF",
            progressive_context_evidence=True,
            budget_invariant_context=True,
            retrieval_evidence_dense_enabled=True,
        )
        signal_guard.raise_if_requested()
        runtime = {
            **dict(session.start(run_id)),
            "orphan_preflight": orphan_preflight,
        }
        runtime_attempt["status"] = "RUNNING"
        runtime_attempt["runtime"] = _json_safe(runtime)
        checkpoint["runtime_attempts"] = runtime_attempts
        checkpoint["phase"] = "RUNTIME_RUNNING"
        _atomic_json(checkpoint_path, checkpoint)
        signal_guard.raise_if_requested()
        counter = _local_token_counter(DEFAULT_TOKENIZER)
        config = replace(
            session.adapter_config(),
            max_limit=MAX_RETRIEVAL_LIMIT,
            allowed_budgets=(EVIDENCE_TOKEN_BUDGET,),
            project_prefix="mvp01-u0-warm",
            barrier_timeout_ms=120_000,
            max_latency_ms=MAX_QUERY_LATENCY_MS,
            capture_profile="MVP01_SYNTHETIC_WARM",
        )
        mcp_log = (runtime_root / f"mcp-attempt-{runtime_attempt_count}.log").open("ab")
        transport = MultiplexedStdioMcpTransport(config.dg14_config(), stderr=mcp_log)
        adapter = DG15MilaiMcpAdapter(
            config,
            token_counter=counter,
            transport=transport,
            close_transport_on_cleanup=False,
        )
        adapter.reset(run_id, fixture.case_id)
        adapter_active = True
        write_started = time.perf_counter()
        adapter.ingest_many(fixture.history_events)
        ingest_ms = (time.perf_counter() - write_started) * 1_000
        readiness = adapter.finalize()
        read_after_write_ms = (time.perf_counter() - write_started) * 1_000
        if readiness.get("status") != "READY":
            raise U0WarmExecutionError("projection barrier did not return READY")
        signal_guard.raise_if_requested()
        for ordinal in range(len(requests) + 1, REQUEST_COUNT + 1):
            request = schedule[ordinal - 1]
            call_cursor = len(adapter.export_call_records())
            checkpoint["in_flight"] = {
                "ordinal": ordinal,
                "request_id": request["request_id"],
                "question_sha256": _digest(request["question"]),
                "runtime_attempt": runtime_attempt_count,
                "call_cursor": call_cursor,
                "marked_at": _now(),
            }
            checkpoint["phase"] = "REQUEST_IN_FLIGHT"
            _atomic_json(checkpoint_path, checkpoint)
            row = _execute_request(
                ordinal=ordinal,
                request=request,
                case=fixture,
                adapter=adapter,
                call_cursor=call_cursor,
            )
            requests.append(row)
            checkpoint["requests"] = requests
            checkpoint["in_flight"] = None
            checkpoint["phase"] = "REQUEST_TERMINAL"
            _atomic_json(checkpoint_path, checkpoint)
            signal_guard.raise_if_requested()
    except (Exception, KeyboardInterrupt, U0WarmInterruption) as exc:  # noqa: BLE001
        shared_error = exc
        in_flight = checkpoint.get("in_flight")
        if isinstance(in_flight, Mapping):
            ordinal = _require_positive_int(
                in_flight.get("ordinal"), "in-flight ordinal"
            )
            request = schedule[ordinal - 1]
            call_cursor = _require_nonnegative_int(
                in_flight.get("call_cursor"), "in-flight call cursor"
            )
            delta_calls = (
                adapter.export_call_records()[call_cursor:]
                if adapter is not None
                else ()
            )
            resolve_calls = tuple(
                record
                for record in delta_calls
                if record.tool_name == "milai_memory_resolve"
            )
            if not (
                len(requests) >= ordinal
                and _is_exact_int(requests[ordinal - 1].get("ordinal"), ordinal)
            ):
                requests.append(
                    _uncertain_request(
                        ordinal,
                        request,
                        exc,
                        logical_mcp_call_delta=len(delta_calls),
                        resolve_calls=resolve_calls,
                        elapsed_ms=None,
                    )
                )
            checkpoint["in_flight"] = None
        if isinstance(exc, U0WarmInterruption):
            # The signal handler only records delivery.  Consume every recorded
            # request here so the terminal ledger cannot lose or double-count it.
            interruption_count += signal_guard.consume_requests()
        elif isinstance(exc, KeyboardInterrupt):
            interruption_count += 1
        for ordinal in range(len(requests) + 1, REQUEST_COUNT + 1):
            requests.append(
                _failure_request(
                    ordinal,
                    schedule[ordinal - 1],
                    exc,
                    attempt_count=0,
                    terminal_type="NOT_ATTEMPTED_SYSTEM_FAILURE",
                )
            )
        checkpoint["requests"] = requests
        checkpoint["interruption_count"] = interruption_count
        checkpoint["phase"] = "REQUESTS_TERMINAL_AFTER_FAILURE"
        _atomic_json(checkpoint_path, checkpoint)

    try:
        if adapter is not None and adapter_active:
            try:
                submitted = adapter.cleanup()
                cleanup = _wait_for_namespace_cleanup(
                    adapter,
                    submitted,
                    timeout_ms=120_000,
                )
            except Exception as exc:  # noqa: BLE001 - lifecycle gate captures this
                cleanup_error = exc
                cleanup = _error_receipt(exc)
        if session is not None:
            try:
                worker_before_close = session.worker_status()
            except Exception as exc:  # noqa: BLE001 - lifecycle gate captures this
                worker_before_close = _error_receipt(exc)
            try:
                projection = session.projection_metrics()
            except Exception as exc:  # noqa: BLE001 - lifecycle gate captures this
                projection = _error_receipt(exc)
        if transport is not None:
            try:
                transport.close()
                transport_cleanup = {"status": "PASS"}
            except Exception as exc:  # noqa: BLE001 - lifecycle gate captures this
                transport_cleanup = _error_receipt(exc)
        if mcp_log is not None:
            try:
                mcp_log.close()
                log_cleanup = {"status": "PASS"}
            except Exception as exc:  # noqa: BLE001 - lifecycle gate captures this
                log_cleanup = _error_receipt(exc)
        if session is not None:
            try:
                runtime_cleanup = session.close()
            except Exception as exc:  # noqa: BLE001 - seal cleanup failure in terminal
                runtime_cleanup = _error_receipt(exc)
        (
            capture_outcome_summary,
            runtime_artifacts,
            diagnostic_manifest_errors,
        ) = _collect_terminal_diagnostic_manifests(
            adapter=adapter,
            runtime_root=runtime_root,
            output_root=output_root,
            mcp_log_path=(runtime_root / f"mcp-attempt-{runtime_attempt_count}.log"),
            run_id=run_id,
        )
        runtime_cleanup = {
            **dict(runtime_cleanup),
            "capture_outcome_summary": dict(capture_outcome_summary),
            "runtime_artifacts": dict(runtime_artifacts),
            "diagnostic_manifest_errors": list(diagnostic_manifest_errors),
        }
        if diagnostic_manifest_errors:
            runtime_cleanup["status"] = "FAIL"
            if shared_error is None:
                shared_error = U0WarmExecutionError(
                    "terminal diagnostic manifest collection failed closed"
                )

        # SIGINT/SIGTERM remain handled throughout cleanup.  A request delivered
        # after the final Context checkpoint is therefore consumed here and makes
        # the terminal lifecycle fail closed instead of being ignored during seal.
        late_interruptions = signal_guard.consume_requests()
        if late_interruptions:
            interruption_count += late_interruptions
            shared_error = U0WarmInterruption(
                "SIGINT_OR_SIGTERM_REQUESTED_DURING_CLEANUP"
            )

        if runtime_attempts:
            runtime_attempts[-1]["status"] = (
                "CLOSED" if runtime_cleanup.get("status") == "PASS" else "CLOSE_FAILED"
            )
            runtime_attempts[-1]["closed_at"] = _now()
            runtime_attempts[-1]["runtime_cleanup"] = _json_safe(runtime_cleanup)
        final_identity_check = _final_identity_check(
            run_id=run_id,
            run_lock=run_lock,
            fixture=fixture,
            schedule=schedule,
            project_root=project_root,
            master_path=master_path,
            goal_path=goal_path,
            env_file=env_file,
        )
        # Atomically define the terminal commit point only after cleanup and the
        # final identity check.  Signals delivered before this barrier are
        # consumed into the FAIL ledger; signals after it are post-terminal.
        seal_interruptions, signal_seal_barrier = signal_guard.begin_seal()
        if seal_interruptions:
            interruption_count += seal_interruptions
            shared_error = U0WarmInterruption(
                "SIGINT_OR_SIGTERM_REQUESTED_BEFORE_ARTIFACT_SEAL"
            )

        lifecycle: dict[str, object] = {
            "runtime": _json_safe(runtime),
            "readiness": _json_safe(readiness),
            "namespace_cleanup": _json_safe(cleanup),
            "worker_before_close": _json_safe(worker_before_close),
            "projection_metrics": _json_safe(projection),
            "runtime_cleanup": _json_safe(runtime_cleanup),
            "transport_cleanup": _json_safe(transport_cleanup),
            "log_cleanup": _json_safe(log_cleanup),
            "capture_outcome_summary": _json_safe(capture_outcome_summary),
            "runtime_artifacts": _json_safe(runtime_artifacts),
            "shared_error": _error_receipt(shared_error) if shared_error else None,
            "cleanup_error": _error_receipt(cleanup_error) if cleanup_error else None,
            "ingest_ms": _rounded(ingest_ms),
            "read_after_write_searchable_ms": _rounded(read_after_write_ms),
            "final_identity_check": dict(final_identity_check),
            "signal_seal_barrier": signal_seal_barrier,
            "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
        checkpoint["schema_version"] = CHECKPOINT_SCHEMA
        checkpoint["phase"] = "LIFECYCLE_TERMINAL"
        checkpoint["requests"] = requests
        checkpoint["in_flight"] = None
        checkpoint["runtime_attempt_count"] = runtime_attempt_count
        checkpoint["runtime_attempts"] = runtime_attempts
        checkpoint["interruption_count"] = interruption_count
        checkpoint["lifecycle"] = lifecycle
        checkpoint["sealed_at"] = _now()
        _atomic_json(checkpoint_path, checkpoint)
        return _seal_warm_artifacts(
            output_root=output_root,
            run_id=run_id,
            run_lock=run_lock,
            run_lock_sha256=run_lock_sha256,
            checkpoint_path=checkpoint_path,
            fixture=fixture,
            requests=requests,
            runtime_attempts=runtime_attempts,
            runtime_attempt_count=runtime_attempt_count,
            interruption_count=interruption_count,
            resumed_after_crash=resumed_after_crash,
            artifact_seal_resumed=False,
            lifecycle=lifecycle,
        )
    finally:
        signal_guard.restore()


def _execute_request(
    *,
    ordinal: int,
    request: Mapping[str, str],
    case: B0RuntimeCase,
    adapter: DG15MilaiMcpAdapter,
    call_cursor: int,
    governance_manifest: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    started = time.perf_counter()
    try:
        result = adapter.query(
            request["question"],
            request["question_at"],
            EVIDENCE_TOKEN_BUDGET,
        )
    except Exception as exc:  # noqa: BLE001 - typed request terminal, no retry
        delta_calls = adapter.export_call_records()[call_cursor:]
        failed_resolve_calls = tuple(
            record
            for record in delta_calls
            if record.tool_name == "milai_memory_resolve"
        )
        failure_class = _failure_class(exc)
        terminal_type = (
            "CONTRACT_FAILURE"
            if failure_class == "PROTOCOL_IMPLEMENTATION"
            else "SYSTEM_FAILURE"
        )
        row = _failure_request(
            ordinal,
            request,
            exc,
            attempt_count=1,
            terminal_type=terminal_type,
            elapsed_ms=(time.perf_counter() - started) * 1_000,
            logical_mcp_call_delta=len(delta_calls),
            resolve_calls=failed_resolve_calls,
        )
        diagnostic = adapter.export_last_resolve_contract_preimage()
        row["raw_response_contract_preimage"] = diagnostic
        if isinstance(diagnostic, Mapping):
            raw_status = diagnostic.get("status")
            if isinstance(raw_status, str):
                row["runtime_status"] = raw_status
                row["runtime_typed_terminal"] = raw_status in {
                    "HIT",
                    "PARTIAL",
                    "CONTESTED",
                    "ABSENT",
                    "ABSTAINED",
                }
                row["runtime_semantic_abstention"] = raw_status in {
                    "ABSENT",
                    "ABSTAINED",
                }
        return row

    outer_ms = (time.perf_counter() - started) * 1_000
    delta_calls = adapter.export_call_records()[call_cursor:]
    resolve_calls = [
        record for record in delta_calls if record.tool_name == "milai_memory_resolve"
    ]
    resolve = resolve_calls[0] if len(resolve_calls) == 1 else None
    evidence_archive = _request_evidence_archive(
        request=request,
        result=result,
        governance_receipts=adapter.export_governance_receipts(),
    )
    evaluation_errors: list[tuple[str, BaseException]] = []
    try:
        _validate_request_evidence_archive(
            evidence_archive,
            mcp_response_sha256=(resolve.response_sha256 if resolve else None),
            governance_manifest=governance_manifest,
        )
        evidence_archive_validated = True
    except Exception as exc:  # noqa: BLE001 - preserve the real Runtime result
        evidence_archive_validated = False
        evaluation_errors.append(("ARCHIVE_VALIDATION", exc))
    try:
        metrics = _context_metrics(case, adapter, result, EVIDENCE_TOKEN_BUDGET)
    except Exception as exc:  # noqa: BLE001 - preserve the real Runtime result
        metrics = None
        evaluation_errors.append(("CONTEXT_METRIC_EVALUATION", exc))

    raw_resolve = result.raw_resolve
    raw_memory_context = raw_resolve.get("memory_context")
    memory_context = (
        raw_memory_context if isinstance(raw_memory_context, Mapping) else {}
    )
    raw_compile_trace = memory_context.get("compile_trace")
    compile_trace = raw_compile_trace if isinstance(raw_compile_trace, Mapping) else {}
    receipt = raw_resolve.get("context_receipt")
    raw_access_trace = raw_resolve.get("access_trace")
    access_trace = raw_access_trace if isinstance(raw_access_trace, Mapping) else {}
    raw_span_links = access_trace.get("span_links")
    span_links = raw_span_links if isinstance(raw_span_links, Mapping) else {}
    selected_ids = memory_context.get("selected_evidence_ids")
    selected_refs = memory_context.get("selected_source_turn_refs")
    selected_identity_valid = (
        isinstance(selected_ids, list)
        and isinstance(selected_refs, list)
        and all(isinstance(value, str) and value for value in selected_ids)
        and all(isinstance(value, str) and value for value in selected_refs)
        and len(selected_ids) == len(selected_refs)
        and len(set(selected_ids)) == len(selected_ids)
        and len(set(selected_refs)) == len(selected_refs)
    )
    selected_count = len(selected_ids) if isinstance(selected_ids, list) else 0
    receipt_present = isinstance(receipt, Mapping)
    exactly_once = len(delta_calls) == 1 and len(resolve_calls) == 1
    runtime_status = result.status
    runtime_typed_terminal = runtime_status in {
        "HIT",
        "PARTIAL",
        "CONTESTED",
        "ABSENT",
        "ABSTAINED",
    }
    runtime_semantic_abstention = runtime_status in {"ABSENT", "ABSTAINED"}
    raw_windows = memory_context.get("windows")
    safe_empty = (
        runtime_semantic_abstention
        and selected_ids == []
        and selected_refs == []
        and raw_resolve.get("items") == []
        and raw_resolve.get("evidence_refs") == []
        and raw_windows == []
        and _is_exact_int(memory_context.get("selected_windows"), 0)
        and receipt is None
    )
    if selected_identity_valid and selected_count > 0:
        context_payload_class = "EVIDENCE_BEARING"
        receipt_requirement = "REQUIRED"
    elif safe_empty:
        context_payload_class = "SAFE_EMPTY"
        receipt_requirement = "NOT_APPLICABLE"
    else:
        context_payload_class = "INVALID"
        receipt_requirement = "INVALID"
    context_receipt_validated: bool | None
    if receipt_requirement == "REQUIRED":
        context_receipt_validated = evidence_archive_validated and receipt_present
    elif receipt_requirement == "NOT_APPLICABLE":
        context_receipt_validated = None
    else:
        context_receipt_validated = False
    context_contract_valid = (
        evidence_archive_validated
        and runtime_typed_terminal
        and context_payload_class in {"EVIDENCE_BEARING", "SAFE_EMPTY"}
        and (
            context_receipt_validated is True
            or receipt_requirement == "NOT_APPLICABLE"
        )
    )
    expected_source_ref_prefix = request["expected_source_ref_prefix"]
    expected_session_anchor_matched = any(
        source_ref.startswith(expected_source_ref_prefix)
        for source_ref in result.selected_source_refs
    )
    expected_anchor_required = request.get("expected_anchor_required", True) is not False
    expected_runtime_status = request.get("expected_runtime_status")
    fixture_expectation_satisfied = _fixture_expectation_satisfied(
        request=request,
        runtime_status=runtime_status,
        context_payload_class=context_payload_class,
        expected_session_anchor_matched=expected_session_anchor_matched,
    )
    hidden_model_calls = compile_trace.get("hidden_model_calls")
    retry_contract_valid = (
        _is_exact_int(access_trace.get("logical_mcp_calls"), 1)
        and _is_exact_int(access_trace.get("automatic_retry_count"), 0)
        and _is_exact_int(access_trace.get("retry_policy_max_retries"), 0)
    )
    metric_contract_valid = _context_truth_metrics_exact(metrics)
    passed = (
        context_contract_valid
        and fixture_expectation_satisfied
        and metric_contract_valid
        and exactly_once
        and result.declared_tokens <= EVIDENCE_TOKEN_BUDGET
        and _is_exact_int(hidden_model_calls, 0)
        and retry_contract_valid
    )
    if passed:
        terminal_type = "CONTEXT_TERMINAL"
        failure_class = None
    elif not context_contract_valid:
        terminal_type = "CONTRACT_FAILURE"
        failure_class = "CONTEXT_CONTRACT"
    elif not fixture_expectation_satisfied:
        terminal_type = "FIXTURE_EXPECTATION_FAILURE"
        failure_class = "FIXTURE_EXPECTATION"
    elif not metric_contract_valid:
        terminal_type = "EVALUATION_FAILURE"
        failure_class = "CONTEXT_TRUTH_METRIC"
    else:
        terminal_type = "EXECUTION_CONTRACT_FAILURE"
        failure_class = "EXECUTION_CONTRACT"
    usage = result.usage
    evaluation_failure_class = (
        "+".join(name for name, _error in evaluation_errors)
        if evaluation_errors
        else None
    )
    primary_error = evaluation_errors[0][1] if evaluation_errors else None
    return {
        "ordinal": ordinal,
        "request_id": request["request_id"],
        "query_class": request["query_class"],
        "question_sha256": _digest(request["question"]),
        "question_at": request["question_at"],
        "expected_source_ref_prefix": expected_source_ref_prefix,
        "expected_anchor_required": expected_anchor_required,
        "expected_runtime_status": expected_runtime_status,
        "expected_session_anchor_matched": expected_session_anchor_matched,
        "fixture_expectation_satisfied": fixture_expectation_satisfied,
        "status": "PASS" if passed else "FAIL",
        "terminal_type": terminal_type,
        "runtime_status": runtime_status,
        "runtime_typed_terminal": runtime_typed_terminal,
        "runtime_semantic_abstention": runtime_semantic_abstention,
        "attempt_count": 1,
        "attempt_certainty": "CERTAIN",
        "resolve_call_count": len(resolve_calls),
        "logical_mcp_call_delta": len(delta_calls),
        "exactly_once": exactly_once,
        "context_payload_class": context_payload_class,
        "context_receipt_requirement": receipt_requirement,
        "context_receipt_validated": context_receipt_validated,
        "context_receipt_sha256": (
            _digest(receipt) if receipt_requirement == "REQUIRED" else None
        ),
        "context_contract_valid": context_contract_valid,
        "semantic_abstention": (
            runtime_semantic_abstention and context_contract_valid
        ),
        "system_failure_as_semantic_abstention": False,
        "answer_quality_status": "NOT_EVALUATED",
        "selected_evidence_count": selected_count,
        "declared_tokens": result.declared_tokens,
        "context_sha256": hashlib.sha256(result.context.encode()).hexdigest(),
        "evidence_archive": evidence_archive,
        "evidence_archive_sha256": _digest(evidence_archive),
        "evidence_archive_validated": evidence_archive_validated,
        "semantic_context_digest": usage.get("semantic_context_digest"),
        "reader_context_digest": usage.get("reader_context_digest"),
        "metrics": metrics,
        "hidden_model_calls": hidden_model_calls,
        "fallback_used": usage.get("fallback_used"),
        "latency_ms": round(result.latency_ms, 6),
        "outer_latency_ms": round(outer_ms, 6),
        "retrieval_ms": _rounded_number(usage.get("retrieval_ms")),
        "context_compile_ms": _rounded_number(usage.get("context_compile_ms")),
        "runtime_request_id": resolve.runtime_request_id if resolve else None,
        "retrieval_trace_id": resolve.retrieval_trace_id if resolve else None,
        "mcp_response_sha256": resolve.response_sha256 if resolve else None,
        "access_logical_mcp_calls": access_trace.get("logical_mcp_calls"),
        "automatic_retry_count": access_trace.get("automatic_retry_count"),
        "retry_policy_max_retries": access_trace.get("retry_policy_max_retries"),
        "access_span_runtime_request_id": span_links.get("runtime_request_id"),
        "access_span_retrieval_trace_id": span_links.get("retrieval_trace_id"),
        "retry_contract_valid": retry_contract_valid,
        "raw_response_contract_preimage": (
            adapter.export_last_resolve_contract_preimage()
        ),
        "mcp_output_limit": False,
        "failure_class": failure_class,
        "evaluation_failure_class": evaluation_failure_class,
        "error": _error_receipt(primary_error) if primary_error is not None else None,
    }


def _fixture_expectation_satisfied(
    *,
    request: Mapping[str, object],
    runtime_status: object,
    context_payload_class: object,
    expected_session_anchor_matched: bool,
) -> bool:
    expected_anchor_required = request.get("expected_anchor_required", True) is not False
    expected_runtime_status = request.get("expected_runtime_status")
    status_satisfied = (
        not isinstance(expected_runtime_status, str)
        or runtime_status == expected_runtime_status
    )
    payload_satisfied = (
        expected_session_anchor_matched
        if expected_anchor_required
        else context_payload_class == "SAFE_EMPTY"
    )
    return status_satisfied and payload_satisfied


def _failure_request(
    ordinal: int,
    request: Mapping[str, str],
    error: BaseException,
    *,
    attempt_count: int,
    terminal_type: str,
    elapsed_ms: float | None = None,
    logical_mcp_call_delta: int | None = 0,
    resolve_calls: Sequence[Any] = (),
    attempt_certainty: str = "CERTAIN",
) -> dict[str, object]:
    resolve = resolve_calls[0] if len(resolve_calls) == 1 else None
    return {
        "ordinal": ordinal,
        "request_id": request["request_id"],
        "query_class": request["query_class"],
        "question_sha256": _digest(request["question"]),
        "question_at": request["question_at"],
        "expected_source_ref_prefix": request["expected_source_ref_prefix"],
        "expected_anchor_required": request.get("expected_anchor_required", True)
        is not False,
        "expected_runtime_status": request.get("expected_runtime_status"),
        "expected_session_anchor_matched": False,
        "fixture_expectation_satisfied": False,
        "status": "FAIL",
        "terminal_type": terminal_type,
        "runtime_status": None,
        "runtime_typed_terminal": False,
        "runtime_semantic_abstention": False,
        "attempt_count": attempt_count,
        "attempt_certainty": attempt_certainty,
        "resolve_call_count": len(resolve_calls),
        "logical_mcp_call_delta": logical_mcp_call_delta,
        "exactly_once": False,
        "context_payload_class": "UNKNOWN",
        "context_receipt_requirement": "UNKNOWN",
        "context_receipt_validated": False,
        "context_receipt_sha256": None,
        "context_contract_valid": False,
        "semantic_abstention": False,
        "system_failure_as_semantic_abstention": False,
        "answer_quality_status": "NOT_EVALUATED",
        "selected_evidence_count": 0,
        "declared_tokens": None,
        "context_sha256": None,
        "evidence_archive": None,
        "evidence_archive_sha256": None,
        "evidence_archive_validated": False,
        "metrics": None,
        "hidden_model_calls": None,
        "fallback_used": None,
        "latency_ms": _rounded(elapsed_ms),
        "outer_latency_ms": _rounded(elapsed_ms),
        "runtime_request_id": (
            resolve.runtime_request_id if resolve is not None else None
        ),
        "retrieval_trace_id": (
            resolve.retrieval_trace_id if resolve is not None else None
        ),
        "mcp_response_sha256": (
            resolve.response_sha256 if resolve is not None else None
        ),
        "access_logical_mcp_calls": None,
        "automatic_retry_count": None,
        "retry_policy_max_retries": None,
        "access_span_runtime_request_id": None,
        "access_span_retrieval_trace_id": None,
        "retry_contract_valid": False,
        "raw_response_contract_preimage": None,
        "mcp_output_limit": _is_mcp_output_limit(error),
        "failure_class": _failure_class(error),
        "evaluation_failure_class": None,
        "error": _error_receipt(error),
    }


def _uncertain_request(
    ordinal: int,
    request: Mapping[str, str],
    error: BaseException,
    *,
    logical_mcp_call_delta: int | None,
    resolve_calls: Sequence[Any],
    elapsed_ms: float | None,
) -> dict[str, object]:
    return _failure_request(
        ordinal,
        request,
        error,
        attempt_count=1,
        attempt_certainty="UNCERTAIN",
        terminal_type="INTERRUPTED_UNCERTAIN_NOT_REPLAYED",
        elapsed_ms=elapsed_ms,
        logical_mcp_call_delta=logical_mcp_call_delta,
        resolve_calls=resolve_calls,
    )


def assess_warm_gate(
    *,
    requests: Sequence[Mapping[str, object]],
    runtime: Mapping[str, object],
    readiness: Mapping[str, object],
    cleanup: Mapping[str, object],
    worker_before_close: Mapping[str, object],
    projection: Mapping[str, object],
    runtime_cleanup: Mapping[str, object],
    transport_cleanup: Mapping[str, object],
    log_cleanup: Mapping[str, object],
    read_after_write_ms: float | None,
    runtime_attempts: Sequence[Mapping[str, object]],
    runtime_attempt_count: int,
    interruption_count: int,
    resumed_after_crash: bool,
    run_lock: Mapping[str, object],
    final_identity_check: Mapping[str, object],
) -> dict[str, object]:
    """Compute the frozen U0 warm gate from request and lifecycle receipts."""

    passed_requests = [row for row in requests if row.get("status") == "PASS"]
    latencies, latency_invalid_count = _timing_samples(requests, "latency_ms")
    outer_latencies, outer_latency_invalid_count = _timing_samples(
        requests, "outer_latency_ms"
    )
    p95 = nearest_rank_percentile(latencies, 0.95)
    outer_p95 = nearest_rank_percentile(outer_latencies, 0.95)
    read_after_write_sample = _optional_number(read_after_write_ms)
    context_terminal_count = len(passed_requests)
    terminal_rate = context_terminal_count / REQUEST_COUNT
    (
        projection_terminal,
        processing_leases,
        expired_leases,
        terminal_lease_residue,
        projection_watermark,
    ) = _projection_terminal(projection)
    persistent_worker = runtime_cleanup.get("persistent_worker")
    runtime_artifacts = runtime_cleanup.get("runtime_artifacts")
    capture_outcome_summary = runtime_cleanup.get("capture_outcome_summary")
    capture_accounting = cleanup.get("capture_accounting")
    runtime_request_ids = [row.get("runtime_request_id") for row in requests]
    retrieval_trace_ids = [row.get("retrieval_trace_id") for row in requests]
    logical_attempt_count = sum(
        value
        for row in requests
        if isinstance((value := row.get("attempt_count")), int)
        and not isinstance(value, bool)
        and value >= 0
    )
    sole_runtime_cleanup = (
        runtime_attempts[0].get("runtime_cleanup")
        if len(runtime_attempts) == 1
        else None
    )
    runtime_attempt_ledger_exact = (
        _is_exact_int(runtime_attempt_count, 1)
        and len(runtime_attempts) == 1
        and _is_exact_int(runtime_attempts[0].get("attempt"), 1)
        and runtime_attempts[0].get("status") == "CLOSED"
        and isinstance(sole_runtime_cleanup, Mapping)
        and sole_runtime_cleanup.get("status") == "PASS"
    )
    readiness_target = readiness.get("target_watermark")
    orphan_preflight = runtime.get("orphan_preflight")
    locked_schedule = _locked_request_schedule(run_lock)
    governance_universe_digests = [
        archive.get("governance_universe_sha256")
        for row in requests
        if isinstance((archive := row.get("evidence_archive")), Mapping)
    ]
    locked_request_identity_exact = len(locked_schedule) == REQUEST_COUNT and all(
        _request_matches_locked_schedule(row, locked_schedule[index], index + 1)
        for index, row in enumerate(requests)
        if index < len(locked_schedule)
    )
    conditions = {
        "request_denominator_exact": len(requests) == REQUEST_COUNT,
        "typed_terminal_coverage": len(requests) == REQUEST_COUNT
        and all(
            isinstance(row.get("terminal_type"), str)
            and row.get("runtime_typed_terminal") is True
            for row in requests
        ),
        "request_and_archive_identity_matches_run_lock": (
            len(requests) == REQUEST_COUNT and locked_request_identity_exact
        ),
        "synthetic_expected_session_anchor_rate_1_0": all(
            _request_has_locked_anchor(row, locked_schedule[index])
            for index, row in enumerate(requests)
            if index < len(locked_schedule)
        )
        and len(requests) == REQUEST_COUNT
        and len(locked_schedule) == REQUEST_COUNT,
        "pass_terminal_contract_exact": all(
            row.get("status") == "PASS"
            and row.get("terminal_type") == "CONTEXT_TERMINAL"
            and row.get("runtime_status")
            in {"HIT", "PARTIAL", "CONTESTED", "ABSENT", "ABSTAINED"}
            and row.get("runtime_typed_terminal") is True
            and row.get("context_contract_valid") is True
            and row.get("fixture_expectation_satisfied") is True
            and row.get("semantic_abstention")
            is (row.get("runtime_status") in {"ABSENT", "ABSTAINED"})
            and row.get("answer_quality_status") == "NOT_EVALUATED"
            for row in requests
        ),
        "context_terminal_rate_1_0": terminal_rate == 1.0,
        "one_runtime_composition_only": runtime_attempt_ledger_exact,
        "interruption_count_zero": _is_exact_int(interruption_count, 0),
        "not_resumed_after_crash": resumed_after_crash is False,
        "logical_attempt_count_exact_100": logical_attempt_count == REQUEST_COUNT,
        "attempt_certainty_rate_1_0": all(
            row.get("attempt_certainty") == "CERTAIN" for row in requests
        ),
        "exactly_once_rate_1_0": all(
            row.get("exactly_once") is True
            and _is_exact_int(row.get("resolve_call_count"), 1)
            and _is_exact_int(row.get("logical_mcp_call_delta"), 1)
            and _is_exact_int(row.get("access_logical_mcp_calls"), 1)
            for row in requests
        ),
        "runtime_request_ids_unique": _unique_nonempty_strings(runtime_request_ids),
        "retrieval_trace_ids_unique": _unique_nonempty_strings(retrieval_trace_ids),
        "access_span_links_exact": all(
            row.get("access_span_runtime_request_id") == row.get("runtime_request_id")
            and row.get("access_span_retrieval_trace_id")
            == row.get("retrieval_trace_id")
            for row in requests
        ),
        "automatic_retry_count_zero": all(
            _is_exact_int(row.get("attempt_count"), 1)
            and _is_exact_int(row.get("automatic_retry_count"), 0)
            and _is_exact_int(row.get("retry_policy_max_retries"), 0)
            and row.get("retry_contract_valid") is True
            for row in requests
        ),
        "missing_required_context_receipt_count_zero": all(
            (
                row.get("context_receipt_requirement") == "REQUIRED"
                and row.get("context_receipt_validated") is True
            )
            or (
                row.get("context_receipt_requirement") == "NOT_APPLICABLE"
                and row.get("context_receipt_validated") is None
            )
            for row in requests
        ),
        "evidence_archive_rate_1_0": all(
            _sealed_request_evidence_valid(row) for row in requests
        ),
        "single_ingest_governance_universe": (
            len(governance_universe_digests) == REQUEST_COUNT
            and all(_valid_sha256(value) for value in governance_universe_digests)
            and len(set(governance_universe_digests)) == 1
        ),
        "mcp_output_limit_count_zero": all(
            row.get("mcp_output_limit") is False for row in requests
        ),
        "fallback_count_zero": all(
            row.get("fallback_used") is False for row in requests
        ),
        "fixture_expectation_satisfied_rate_1_0": all(
            row.get("fixture_expectation_satisfied") is True for row in requests
        ),
        "system_failure_as_semantic_abstention_count_zero": all(
            row.get("system_failure_as_semantic_abstention") is False
            for row in requests
        ),
        "context_truth_metrics_exact": all(
            _context_truth_metrics_exact(row.get("metrics")) for row in requests
        ),
        "evidence_token_cap": all(
            isinstance((value := row.get("declared_tokens")), int)
            and not isinstance(value, bool)
            and value >= 0
            and value <= EVIDENCE_TOKEN_BUDGET
            for row in requests
        ),
        "hidden_model_calls_zero": all(
            _is_exact_int(row.get("hidden_model_calls"), 0) for row in requests
        ),
        "latency_sample_coverage_100": len(latencies) == REQUEST_COUNT
        and latency_invalid_count == 0,
        "outer_latency_sample_coverage_100": len(outer_latencies) == REQUEST_COUNT
        and outer_latency_invalid_count == 0,
        "retrieval_context_p95_le_2000_ms": p95 is not None
        and p95 <= MAX_QUERY_LATENCY_MS,
        "warm_memory_control_p95_le_500_ms": outer_p95 is not None
        and outer_p95 <= WARM_MEMORY_CONTROL_P95_MS,
        "read_after_write_within_60s": _nonnegative_number_at_most(
            read_after_write_ms, READ_AFTER_WRITE_MAX_MS
        ),
        "read_after_write_single_batch_le_5000_ms": _nonnegative_number_at_most(
            read_after_write_ms, READ_AFTER_WRITE_TARGET_MS
        ),
        "runtime_synthetic_only": runtime.get("data_mode") == "SYNTHETIC_ONLY",
        "owned_orphan_preflight_pass": (
            isinstance(orphan_preflight, Mapping)
            and orphan_preflight.get("status") == "PASS"
        ),
        "runtime_retrieval_identity_matches_lock": _runtime_identity_matches_lock(
            runtime, run_lock
        ),
        "final_code_asset_authority_identity_pass": final_identity_check.get("status")
        == "PASS",
        "projection_barrier_ready": readiness.get("status") == "READY",
        "namespace_cleanup_terminal": cleanup.get("cleanup_terminal") is True,
        "namespace_cleanup_denominator_exact": (
            _is_exact_int(cleanup.get("evidence_count"), FIXTURE_EVENT_COUNT)
            and _is_exact_int(cleanup.get("accepted_count"), FIXTURE_EVENT_COUNT)
            and _is_exact_int(cleanup.get("failed_count"), 0)
            and _is_exact_int(
                cleanup.get("projection_purged_count"), FIXTURE_EVENT_COUNT
            )
            and _is_exact_int(
                cleanup.get("primary_bytes_terminal_count"), FIXTURE_EVENT_COUNT
            )
            and _is_exact_int(
                cleanup.get("primary_bytes_erased_count"), FIXTURE_EVENT_COUNT
            )
        ),
        "capture_accounting_exact": _successful_capture_accounting(capture_accounting),
        "capture_outcome_manifest_exact": _successful_capture_outcome_manifest(
            capture_outcome_summary
        ),
        "runtime_artifact_manifest_exact": _valid_runtime_artifact_manifest(
            runtime_artifacts,
            expected_run_id=run_lock.get("run_id"),
            expected_database=runtime.get("database"),
            expected_api_pid=runtime.get("api_pid"),
            expected_worker_pid=runtime.get("worker_pid"),
        ),
        "runtime_database_cleanup_identity_exact": (
            _runtime_database_cleanup_identity_exact(
                runtime=runtime,
                runtime_cleanup=runtime_cleanup,
                runtime_artifacts=runtime_artifacts,
            )
        ),
        "runtime_process_release_identity_exact": (
            _runtime_process_release_identity_exact(
                runtime=runtime,
                runtime_artifacts=runtime_artifacts,
            )
        ),
        "runtime_artifacts_reverified_at_seal": (
            runtime_cleanup.get("runtime_artifact_seal_reverified") is True
        ),
        "worker_running_before_close": worker_before_close.get("status") == "RUNNING",
        "worker_unexpected_exit_zero": worker_before_close.get("return_code") is None,
        "projection_deliveries_terminal": projection_terminal,
        "projection_watermark_covers_readiness": (
            isinstance(readiness_target, int)
            and not isinstance(readiness_target, bool)
            and readiness_target >= 0
            and projection_watermark is not None
            and projection_watermark >= readiness_target
        ),
        "processing_lease_after_drain_zero": processing_leases == 0,
        "expired_lease_after_drain_zero": expired_leases == 0,
        "terminal_lease_residue_zero": terminal_lease_residue == 0,
        "runtime_cleanup_pass": runtime_cleanup.get("status") == "PASS",
        "transport_cleanup_pass": transport_cleanup.get("status") == "PASS",
        "log_cleanup_pass": log_cleanup.get("status") == "PASS",
        "worker_cleanup_return_zero": (
            isinstance(persistent_worker, Mapping)
            and persistent_worker.get("status") == "STOPPED"
            and _is_exact_int(persistent_worker.get("return_code"), 0)
        ),
    }
    return {
        "passed": all(conditions.values()),
        "conditions": conditions,
        "context_terminal_count": context_terminal_count,
        "context_terminal_rate": terminal_rate,
        "typed_terminal_count": len(requests),
        "logical_attempt_count": logical_attempt_count,
        "runtime_attempt_count": runtime_attempt_count,
        "interruption_count": interruption_count,
        "semantic_abstention_count": sum(
            row.get("semantic_abstention") is True for row in requests
        ),
        "failure_class_counts": dict(
            sorted(
                Counter(
                    str(row.get("failure_class"))
                    for row in requests
                    if row.get("failure_class") is not None
                ).items()
            )
        ),
        "request_latency_ms": {
            "sample_count": len(latencies),
            "invalid_count": latency_invalid_count,
            "p50": _rounded(nearest_rank_percentile(latencies, 0.50)),
            "p95": _rounded(p95),
            "max": _rounded(max(latencies)) if latencies else None,
        },
        "warm_memory_control_outer_ms": {
            "sample_count": len(outer_latencies),
            "invalid_count": outer_latency_invalid_count,
            "p50": _rounded(nearest_rank_percentile(outer_latencies, 0.50)),
            "p95": _rounded(outer_p95),
            "max": _rounded(max(outer_latencies)) if outer_latencies else None,
        },
        "read_after_write_searchable_ms": _rounded(read_after_write_sample),
        "read_after_write_single_batch_target_met": _nonnegative_number_at_most(
            read_after_write_ms, READ_AFTER_WRITE_TARGET_MS
        ),
        "expired_lease_after_drain_count": expired_leases,
        "processing_lease_after_drain_count": processing_leases,
        "terminal_lease_residue_count": terminal_lease_residue,
        "projection_terminal_watermark": projection_watermark,
    }


def _successful_capture_accounting(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    expected_counts = {
        "submitted_call_count": FIXTURE_EVENT_COUNT,
        "returned_success_count": FIXTURE_EVENT_COUNT,
        "returned_failure_count": 0,
        "ambiguous_success_count": 0,
        "unknown_outcome_count": 0,
        "registered_evidence_count": FIXTURE_EVENT_COUNT,
        "runtime_evidence_count": FIXTURE_EVENT_COUNT,
        "returned_success_unregistered_count": 0,
        "runtime_unregistered_evidence_count": 0,
    }
    return (
        all(
            _is_exact_int(value.get(key), expected)
            for key, expected in expected_counts.items()
        )
        and value.get("registered_denominator_matches_runtime") is True
        and value.get("attempted_outcome_denominator_exact") is True
    )


def _successful_capture_outcome_manifest(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    records = value.get("records")
    stages = value.get("stage_records")
    if not isinstance(records, list) or not isinstance(stages, list):
        return False
    manifest_payload = {
        key: item for key, item in value.items() if key != "manifest_sha256"
    }
    request_ids = [
        record.get("runtime_request_id")
        for record in records
        if isinstance(record, Mapping)
    ]
    return (
        value.get("status") == "OBSERVED"
        and _is_exact_int(value.get("capture_record_count"), FIXTURE_EVENT_COUNT)
        and _is_exact_int(value.get("succeeded_record_count"), FIXTURE_EVENT_COUNT)
        and _is_exact_int(value.get("failed_record_count"), 0)
        and len(records) == FIXTURE_EVENT_COUNT
        and len(stages) >= 1
        and all(
            isinstance(record, Mapping)
            and record.get("status") == "SUCCEEDED"
            and record.get("error_code") is None
            and _valid_sha256(record.get("request_sha256"))
            and _valid_sha256(record.get("response_sha256"))
            for record in records
        )
        and len(request_ids) == FIXTURE_EVENT_COUNT
        and all(isinstance(item, str) and item for item in request_ids)
        and len(set(request_ids)) == FIXTURE_EVENT_COUNT
        and value.get("records_sha256") == _digest(records)
        and value.get("stage_records_sha256") == _digest(stages)
        and value.get("manifest_sha256") == _digest(manifest_payload)
    )


def _valid_runtime_artifact_manifest(
    value: object,
    *,
    expected_run_id: object,
    expected_database: object,
    expected_api_pid: object,
    expected_worker_pid: object,
) -> bool:
    if (
        not isinstance(value, Mapping)
        or not isinstance(expected_run_id, str)
        or not isinstance(expected_database, str)
        or not isinstance(expected_api_pid, int)
        or isinstance(expected_api_pid, bool)
        or not isinstance(expected_worker_pid, int)
        or isinstance(expected_worker_pid, bool)
    ):
        return False
    files = value.get("files")
    ownership = value.get("ownership")
    if not isinstance(files, Mapping) or not isinstance(ownership, Mapping):
        return False
    manifest_payload = {
        key: item for key, item in value.items() if key != "manifest_sha256"
    }
    expected_paths = {
        "mcp_log": "runtime/attempt-001/mcp-attempt-1.log",
        "runtime_log": "runtime/attempt-001/runtime.log",
        "runtime_ownership": "runtime/attempt-001/runtime-ownership.json",
    }
    return (
        value.get("status") == "PASS"
        and value.get("runtime_root") == "runtime/attempt-001"
        and value.get("all_files_present") is True
        and value.get("ownership_released") is True
        and value.get("ownership_processes_recorded") is True
        and value.get("diagnostic_errors") == []
        and set(files) == set(expected_paths)
        and all(
            isinstance(entry, Mapping)
            and entry.get("present") is True
            and entry.get("path") == expected_paths[name]
            and isinstance(entry.get("size_bytes"), int)
            and not isinstance(entry.get("size_bytes"), bool)
            and int(entry["size_bytes"]) >= 0
            and _valid_sha256(entry.get("sha256"))
            for name, entry in files.items()
        )
        and ownership.get("schema_version") == "milai-local-runtime-ownership-v0.1"
        and ownership.get("status") == "RELEASED"
        and ownership.get("run_id") == expected_run_id
        and ownership.get("database") == expected_database
        and _owned_process_identity_matches(
            ownership.get("api_process"),
            expected_pid=expected_api_pid,
            expected_executable="milai-api",
        )
        and _owned_process_identity_matches(
            ownership.get("worker_process"),
            expected_pid=expected_worker_pid,
            expected_executable="milai-worker",
        )
        and value.get("manifest_sha256") == _digest(manifest_payload)
    )


def _runtime_database_cleanup_identity_exact(
    *,
    runtime: Mapping[str, object],
    runtime_cleanup: Mapping[str, object],
    runtime_artifacts: object,
) -> bool:
    database = runtime.get("database")
    ownership = (
        runtime_artifacts.get("ownership")
        if isinstance(runtime_artifacts, Mapping)
        else None
    )
    return (
        isinstance(database, str)
        and database.startswith("milai_smoke_dg14_")
        and len(database) <= 63
        and runtime.get("ephemeral") is True
        and runtime_cleanup.get("status") == "PASS"
        and runtime_cleanup.get("database") == database
        and runtime_cleanup.get("exact_fresh_database_only") is True
        and runtime_cleanup.get("owner") == "milai_owner"
        and _is_exact_int(runtime_cleanup.get("connections_before_drop"), 0)
        and isinstance(ownership, Mapping)
        and ownership.get("database") == database
        and ownership.get("status") == "RELEASED"
    )


def _runtime_process_release_identity_exact(
    *,
    runtime: Mapping[str, object],
    runtime_artifacts: object,
) -> bool:
    ownership = (
        runtime_artifacts.get("ownership")
        if isinstance(runtime_artifacts, Mapping)
        else None
    )
    if not isinstance(ownership, Mapping):
        return False
    api_process = ownership.get("api_process")
    worker_process = ownership.get("worker_process")
    return (
        _owned_process_identity_matches(
            api_process,
            expected_pid=runtime.get("api_pid"),
            expected_executable="milai-api",
        )
        and _owned_process_identity_matches(
            worker_process,
            expected_pid=runtime.get("worker_pid"),
            expected_executable="milai-worker",
        )
        and _owned_process_absent(api_process)
        and _owned_process_absent(worker_process)
    )


def _wait_for_namespace_cleanup(
    adapter: DG15MilaiMcpAdapter,
    submitted: Mapping[str, object],
    *,
    timeout_ms: int,
    poll_interval_ms: int = 100,
) -> dict[str, object]:
    accepted = submitted.get("accepted_count")
    evidence_count = submitted.get("evidence_count")
    failed_count = submitted.get("failed_count")
    if (
        not isinstance(accepted, int)
        or isinstance(accepted, bool)
        or accepted < 0
        or not isinstance(evidence_count, int)
        or isinstance(evidence_count, bool)
        or not 0 <= evidence_count <= FIXTURE_EVENT_COUNT
        or not isinstance(failed_count, int)
        or isinstance(failed_count, bool)
        or failed_count < 0
        or accepted != evidence_count
        or failed_count != 0
    ):
        raise DG14ContractError("namespace cleanup submission counts are invalid")
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
            raise DG14ContractError("namespace cleanup terminal counts are invalid")
        if counts["accepted_count"] != accepted or counts["failed_count"] != 0:
            raise DG14ContractError("namespace cleanup denominator drifted")
        elapsed_ms = (time.perf_counter() - started) * 1_000
        if (
            counts["projection_purged_count"] == accepted
            and counts["primary_bytes_terminal_count"] == accepted
            and counts["primary_bytes_erased_count"] == accepted
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
            raise U0WarmExecutionError("namespace cleanup did not reach terminal state")
        time.sleep(poll_interval_ms / 1_000)


def _projection_terminal(
    value: Mapping[str, object],
) -> tuple[bool, int, int, int, int | None]:
    deliveries = value.get("deliveries")
    terminal = isinstance(deliveries, list) and len(deliveries) == len(
        EXPECTED_PROJECTION_DELIVERIES
    )
    row_identities: set[tuple[str, str, str, str]] = set()
    for item in deliveries if isinstance(deliveries, list) else ():
        if not isinstance(item, Mapping):
            terminal = False
            continue
        projection = item.get("projection")
        event_type = item.get("event_type")
        applicability = item.get("applicability")
        handler_outcome = item.get("handler_outcome")
        state = item.get("state")
        logical_items = item.get("logical_items")
        attempts = item.get("attempts")
        latency = item.get("queue_to_delivery_ms")
        if not all(
            isinstance(field, str) and field
            for field in (
                projection,
                event_type,
                applicability,
                handler_outcome,
                state,
            )
        ):
            terminal = False
            continue
        assert isinstance(projection, str)
        assert isinstance(event_type, str)
        assert isinstance(applicability, str)
        assert isinstance(handler_outcome, str)
        assert isinstance(state, str)
        identity = (projection, event_type, applicability, handler_outcome)
        terminal = terminal and identity not in row_identities
        row_identities.add(identity)
        terminal = terminal and (
            identity in EXPECTED_PROJECTION_DELIVERIES
            and state == "DELIVERED"
            and isinstance(logical_items, int)
            and not isinstance(logical_items, bool)
            and logical_items == EXPECTED_PROJECTION_LOGICAL_ITEMS
            and isinstance(attempts, int)
            and not isinstance(attempts, bool)
            and attempts == EXPECTED_PROJECTION_LOGICAL_ITEMS
            and isinstance(latency, (int, float))
            and not isinstance(latency, bool)
            and math.isfinite(float(latency))
            and float(latency) >= 0.0
        )
    terminal = terminal and row_identities == EXPECTED_PROJECTION_DELIVERIES
    watermarks = value.get("watermarks")
    watermark: int | None = None
    if isinstance(watermarks, Mapping) and set(watermarks) == EXPECTED_PROJECTIONS:
        values = list(watermarks.values())
        if (
            all(
                isinstance(item, int) and not isinstance(item, bool) and item >= 0
                for item in values
            )
            and len(set(values)) == 1
        ):
            watermark = int(values[0])
            terminal = terminal and (
                watermark == EXPECTED_PROJECTION_TERMINAL_WATERMARK
            )
        else:
            terminal = False
    else:
        terminal = False
    lease_health = value.get("lease_health")
    lease_counts: list[int] = []
    if isinstance(lease_health, Mapping):
        for key in (
            "processing_count",
            "expired_processing_count",
            "terminal_lease_residue_count",
        ):
            raw = lease_health.get(key)
            if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
                lease_counts.append(raw)
            else:
                lease_counts.append(-1)
                terminal = False
    else:
        lease_counts = [-1, -1, -1]
        terminal = False
    return (
        terminal,
        lease_counts[0],
        lease_counts[1],
        lease_counts[2],
        watermark,
    )


def _timing_samples(
    requests: Sequence[Mapping[str, object]], key: str
) -> tuple[list[float], int]:
    values: list[float] = []
    invalid = 0
    for row in requests:
        raw = row.get(key)
        if (
            not isinstance(raw, (int, float))
            or isinstance(raw, bool)
            or not math.isfinite(float(raw))
            or float(raw) < 0.0
        ):
            invalid += 1
            continue
        values.append(float(raw))
    return values, invalid


def _unique_nonempty_strings(values: Sequence[object]) -> bool:
    return (
        len(values) == REQUEST_COUNT
        and all(isinstance(value, str) and value for value in values)
        and len(set(values)) == REQUEST_COUNT
    )


def _runtime_identity_matches_lock(
    runtime: Mapping[str, object], run_lock: Mapping[str, object]
) -> bool:
    retrieval = run_lock.get("retrieval_runtime")
    if not isinstance(retrieval, Mapping):
        return False
    embedding = retrieval.get("embedding")
    reranker = retrieval.get("reranker")
    if not isinstance(embedding, Mapping) or not isinstance(reranker, Mapping):
        return False
    source_dimensions = embedding.get("source_dimensions")
    projection_dimensions = embedding.get("projection_dimensions")
    max_concurrency = embedding.get("max_concurrency")
    prewarm = embedding.get("prewarm")
    if (
        not isinstance(source_dimensions, int)
        or isinstance(source_dimensions, bool)
        or not isinstance(projection_dimensions, int)
        or isinstance(projection_dimensions, bool)
        or not isinstance(max_concurrency, int)
        or isinstance(max_concurrency, bool)
        or not isinstance(prewarm, bool)
    ):
        return False
    return (
        runtime.get("embedding_provider") == embedding.get("provider")
        and runtime.get("embedding_model_id") == embedding.get("model_id")
        and runtime.get("embedding_model_path") == embedding.get("model_path")
        and _is_exact_int(runtime.get("embedding_source_dimensions"), source_dimensions)
        and _is_exact_int(
            runtime.get("embedding_projection_dimensions"), projection_dimensions
        )
        and runtime.get("embedding_prewarm") is prewarm
        and _is_exact_int(runtime.get("embedding_max_concurrency"), max_concurrency)
        and runtime.get("retrieval_reranker_provider") == reranker.get("provider")
        and runtime.get("retrieval_reranker_provider") == "none"
        and runtime.get("retrieval_evidence_dense_enabled")
        is retrieval.get("evidence_dense_enabled")
        and runtime.get("retrieval_evidence_dense_enabled") is True
    )


def _locked_request_schedule(
    run_lock: Mapping[str, object],
) -> list[Mapping[str, object]]:
    raw_schedule = run_lock.get("request_schedule")
    if not isinstance(raw_schedule, Mapping):
        return []
    raw_requests = raw_schedule.get("requests")
    if not isinstance(raw_requests, list) or any(
        not isinstance(item, Mapping) for item in raw_requests
    ):
        return []
    requests = [item for item in raw_requests if isinstance(item, Mapping)]
    if (
        not _is_exact_int(raw_schedule.get("request_count"), REQUEST_COUNT)
        or len(requests) != REQUEST_COUNT
        or raw_schedule.get("requests_sha256") != _digest(requests)
    ):
        return []
    return requests


def _request_matches_locked_schedule(
    row: Mapping[str, object], locked: Mapping[str, object], ordinal: int
) -> bool:
    archive = row.get("evidence_archive")
    if not isinstance(archive, Mapping):
        return False
    archived_request = archive.get("request")
    selected_refs = archive.get("selected_source_turn_refs")
    expected_prefix = locked.get("expected_source_ref_prefix")
    if (
        not isinstance(archived_request, Mapping)
        or not isinstance(selected_refs, list)
        or not all(isinstance(value, str) and value for value in selected_refs)
        or not isinstance(expected_prefix, str)
        or not expected_prefix
    ):
        return False
    question = archived_request.get("question")
    return (
        _is_exact_int(row.get("ordinal"), ordinal)
        and _is_exact_int(locked.get("ordinal"), ordinal)
        and row.get("request_id") == locked.get("request_id")
        and row.get("query_class") == locked.get("query_class")
        and row.get("question_sha256") == locked.get("question_sha256")
        and row.get("question_at") == locked.get("question_at")
        and row.get("expected_source_ref_prefix") == expected_prefix
        and row.get("expected_session_anchor_matched") is True
        and row.get("fixture_expectation_satisfied") is True
        and row.get("status") == "PASS"
        and row.get("terminal_type") == "CONTEXT_TERMINAL"
        and row.get("runtime_status")
        in {"HIT", "PARTIAL", "CONTESTED", "ABSTAINED"}
        and row.get("runtime_typed_terminal") is True
        and row.get("context_contract_valid") is True
        and archived_request.get("request_id") == locked.get("request_id")
        and archived_request.get("query_class") == locked.get("query_class")
        and isinstance(question, str)
        and _digest(question) == locked.get("question_sha256")
        and archived_request.get("question_at") == locked.get("question_at")
        and archived_request.get("expected_source_ref_prefix") == expected_prefix
        and _request_has_locked_anchor(row, locked)
    )


def _request_has_locked_anchor(
    row: Mapping[str, object], locked: Mapping[str, object]
) -> bool:
    archive = row.get("evidence_archive")
    expected_prefix = locked.get("expected_source_ref_prefix")
    if not isinstance(archive, Mapping) or not isinstance(expected_prefix, str):
        return False
    selected_refs = archive.get("selected_source_turn_refs")
    return (
        row.get("expected_session_anchor_matched") is True
        and isinstance(selected_refs, list)
        and bool(selected_refs)
        and all(isinstance(value, str) and value for value in selected_refs)
        and any(value.startswith(expected_prefix) for value in selected_refs)
    )


def _validate_warm_capture_contract(
    *,
    run_id: str,
    fixture: B0RuntimeCase,
    project_root: Path,
) -> dict[str, object]:
    """Validate every exact warm wire payload against Runtime before any process starts."""

    runtime_src = project_root / "runtime/src"
    if str(runtime_src) not in sys.path:
        sys.path.insert(0, str(runtime_src))
    from milai.domain import EvidenceIngestRequest
    from pydantic import ValidationError

    expected_model_source = (
        project_root / "runtime/src/milai/domain/evidence.py"
    ).resolve()
    actual_model_source = Path(inspect.getfile(EvidenceIngestRequest)).resolve()
    if actual_model_source != expected_model_source:
        raise U0WarmExecutionError(
            "warm capture Runtime model import identity drifted: "
            f"expected {expected_model_source}, got {actual_model_source}"
        )

    transport = _CaptureContractTransport()
    adapter = DG15MilaiMcpAdapter(
        DG15AdapterConfig(
            base_url="http://127.0.0.1:1",
            executable=project_root / "integrations/mcp/.venv/bin/milai-mcp",
            profile_tokens={
                "submitter": "s" * 32,
                "reviewer": "r" * 32,
                "reader-detail": "d" * 32,
                "operator": "o" * 32,
            },
            project_prefix="mvp01-u0-warm",
            capture_profile="MVP01_SYNTHETIC_WARM",
        ),
        token_counter=lambda _text: 0,
        transport=cast(MultiplexedStdioMcpTransport, transport),
    )
    adapter.reset(run_id, fixture.case_id)
    expected_source_context_keys = {
        "session_id",
        "turn_id",
        "turn_ordinal",
        "round_id",
        "round_ordinal",
        "previous_turn_id",
        "next_turn_id",
    }
    payload_receipts: list[dict[str, object]] = []
    for event in fixture.history_events:
        arguments = adapter._capture_arguments(event)
        source_context = arguments.get("source_context")
        if not isinstance(source_context, Mapping):
            raise U0WarmExecutionError("warm capture source_context is not a mapping")
        wire_payload = {
            key: value
            for key, value in arguments.items()
            if key not in {"operation_id", "confirmation"}
        }
        try:
            validated = EvidenceIngestRequest.model_validate(wire_payload)
        except ValidationError as exc:
            fields = [
                {
                    "path": ".".join(str(part) for part in issue["loc"]),
                    "type": issue["type"],
                }
                for issue in exc.errors(include_url=False, include_input=False)
            ]
            raise U0WarmExecutionError(
                "warm capture Runtime schema preflight failed: "
                + json.dumps(fields, sort_keys=True, separators=(",", ":"))
            ) from exc
        if set(source_context) != expected_source_context_keys:
            raise U0WarmExecutionError(
                "warm capture source_context differs from the Runtime wire contract"
            )
        payload_receipts.append(
            {
                "event_id": event.event_id,
                "payload_sha256": _digest(validated.model_dump(mode="json")),
            }
        )
    if len(payload_receipts) != FIXTURE_EVENT_COUNT:
        raise U0WarmExecutionError("warm capture schema preflight denominator drifted")
    return {
        "status": "PASS",
        "profile": "MVP01_SYNTHETIC_WARM",
        "runtime_model": "milai.domain.EvidenceIngestRequest",
        "runtime_model_source_path": str(
            actual_model_source.relative_to(project_root.resolve())
        ),
        "runtime_model_source_sha256": _sha256_file(actual_model_source),
        "runtime_model_json_schema_sha256": _digest(
            EvidenceIngestRequest.model_json_schema()
        ),
        "event_count": len(payload_receipts),
        "source_context_keys": sorted(expected_source_context_keys),
        "payload_receipts_sha256": _digest(payload_receipts),
        "payload_receipts": payload_receipts,
    }


def _build_run_lock(
    *,
    run_id: str,
    authority: WarmAuthorityReceipt,
    predecessor: Mapping[str, object],
    fixture: B0RuntimeCase,
    schedule: Sequence[Mapping[str, str]],
    project_root: Path,
    env_file: Path,
) -> dict[str, object]:
    code_paths = (
        Path(__file__),
        project_root / "evals/mvp01/u0_warm_contract.py",
        project_root / "scripts/run_mvp01_u0_warm_soak.py",
        project_root / "evals/dg14/benchmark.py",
        project_root / "evals/dg14/contracts.py",
        project_root / "evals/dg14/reader_token_accounting.py",
        project_root / "evals/dg15/contracts.py",
        project_root / "evals/dg15/runtime_session.py",
        project_root / "evals/dg15/milai_mcp_adapter.py",
        project_root / "evals/dg15/mcp_stdio.py",
        project_root / "evals/gdpm/b0_canary_runtime.py",
        project_root / "evals/gdpm/b0_canary_runner.py",
        project_root / "evals/gdpm/b0_canary_longmemeval.py",
        project_root / "integrations/mcp/src/milai_mcp/server.py",
        project_root / "runtime/src/milai/application/memory_context.py",
        project_root / "runtime/src/milai/persistence/projection_repository.py",
        project_root / "runtime/src/milai/workers/main.py",
    )
    identities = {
        str(path.resolve().relative_to(project_root.resolve())): _sha256_file(path)
        for path in code_paths
    }
    causal_trees = {
        "runtime_source": _tree_manifest(
            project_root / "runtime/src/milai", project_root=project_root
        ),
        "runtime_migrations": _tree_manifest(
            project_root / "runtime/migrations", project_root=project_root
        ),
        "mcp_source": _tree_manifest(
            project_root / "integrations/mcp/src", project_root=project_root
        ),
    }
    environment_paths = (
        project_root / "runtime/pyproject.toml",
        project_root / "runtime/uv.lock",
        project_root / "runtime/.venv/bin/milai-api",
        project_root / "runtime/.venv/bin/milai-worker",
        project_root / "integrations/mcp/pyproject.toml",
        project_root / "integrations/mcp/uv.lock",
        project_root / "integrations/mcp/.venv/bin/milai-mcp",
        Path(sys.executable).resolve(),
    )
    execution_environment = {
        "python_version": sys.version,
        "python_implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "platform_system": platform.system(),
        "file_identities": {
            str(path.resolve()): _sha256_file(path) for path in environment_paths
        },
    }
    tokenizer_sha256 = _sha256_file(DEFAULT_TOKENIZER)
    chat_template_sha256 = _sha256_file(DEFAULT_CHAT_TEMPLATE)
    if tokenizer_sha256 != EXPECTED_TOKENIZER_SHA256:
        raise U0WarmExecutionError("frozen Reader tokenizer digest drifted")
    if chat_template_sha256 != EXPECTED_CHAT_TEMPLATE_SHA256:
        raise U0WarmExecutionError("frozen Reader chat template digest drifted")
    schedule_receipts = [
        {
            "ordinal": ordinal,
            "request_id": row["request_id"],
            "query_class": row["query_class"],
            "question_sha256": _digest(row["question"]),
            "question_at": row["question_at"],
            "expected_source_ref_prefix": row["expected_source_ref_prefix"],
        }
        for ordinal, row in enumerate(schedule, start=1)
    ]
    retrieval_runtime = _retrieval_runtime_manifest(
        env_file=env_file,
        project_root=project_root,
        evidence_dense_enabled=True,
    )
    capture_contract_preflight = _validate_warm_capture_contract(
        run_id=run_id,
        fixture=fixture,
        project_root=project_root,
    )
    return {
        "schema_version": "mila-mvp01-u0-warm-run-lock-v0.3",
        "run_id": run_id,
        "created_at": _now(),
        "scope": SCOPE_IDENTITY,
        "authority": asdict(authority),
        "previous_gate": dict(predecessor),
        "execution_plan": {
            "composition": "ONE_FRESH_POSTGRES_RUNTIME_WORKER_STDIO_MCP",
            "data_mode": "SYNTHETIC_ONLY",
            "request_count": REQUEST_COUNT,
            "logical_attempts_per_request": 1,
            "automatic_retry_count": AUTOMATIC_RETRY_COUNT,
            "workers": 1,
            "mcp_concurrency": 4,
            "projection_batch_size": 64,
            "memory_formation_mode": "OFF",
            "capture_profile": "MVP01_SYNTHETIC_WARM",
            "max_retrieval_limit": MAX_RETRIEVAL_LIMIT,
            "retrieval_evidence_dense_enabled": True,
            "evidence_token_budget": EVIDENCE_TOKEN_BUDGET,
            "max_query_latency_ms": MAX_QUERY_LATENCY_MS,
            "warm_memory_control_p95_ms": WARM_MEMORY_CONTROL_P95_MS,
            "read_after_write_target_ms": READ_AFTER_WRITE_TARGET_MS,
            "read_after_write_max_ms": READ_AFTER_WRITE_MAX_MS,
            "planner_reranker_reader_answer_judge_calls": 0,
            "benchmark_case_count": 0,
            "formal_holdout_consumed": False,
        },
        "fixture": _fixture_manifest(fixture),
        "capture_contract_preflight": capture_contract_preflight,
        "request_schedule": {
            "request_count": len(schedule_receipts),
            "query_class_counts": dict(
                sorted(Counter(row["query_class"] for row in schedule).items())
            ),
            "requests_sha256": _digest(schedule_receipts),
            "requests": schedule_receipts,
        },
        "code_identities": identities,
        "causal_tree_identities": causal_trees,
        "execution_environment": execution_environment,
        "reader_assets": {
            "tokenizer": {
                "path": str(DEFAULT_TOKENIZER),
                "sha256": tokenizer_sha256,
            },
            "chat_template": {
                "path": str(DEFAULT_CHAT_TEMPLATE),
                "sha256": chat_template_sha256,
            },
        },
        "retrieval_runtime": retrieval_runtime,
    }


def _fixture_manifest(case: B0RuntimeCase) -> dict[str, object]:
    events = [event.canonical() for event in case.history_events]
    return {
        "schema_version": "mila-mvp01-u0-warm-fixture-v0.1",
        "case_id": case.case_id,
        "classification": "SYNTHETIC_ONLY",
        "session_count": len({event.session_ordinal for event in case.history_events}),
        "event_count": len(events),
        "events_sha256": _digest(events),
    }


def _tree_manifest(root: Path, *, project_root: Path) -> dict[str, object]:
    if not root.is_dir():
        raise U0WarmExecutionError(f"causal source tree is absent: {root}")
    files = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    ]
    if not files:
        raise U0WarmExecutionError(f"causal source tree is empty: {root}")
    entries = [
        {
            "path": str(path.resolve().relative_to(project_root.resolve())),
            "sha256": _sha256_file(path),
        }
        for path in files
    ]
    return {
        "root": str(root.resolve().relative_to(project_root.resolve())),
        "file_count": len(entries),
        "tree_sha256": _digest(entries),
        "files": entries,
    }


def _final_identity_check(
    *,
    run_id: str,
    run_lock: Mapping[str, object],
    fixture: B0RuntimeCase,
    schedule: Sequence[Mapping[str, str]],
    project_root: Path,
    master_path: Path,
    goal_path: Path,
    env_file: Path,
) -> dict[str, object]:
    try:
        final_authority = assert_mvp01_u0_warm_authorized(
            master_path=master_path,
            goal_path=goal_path,
        )
        final_predecessor = assert_previous_u0_gate(project_root)
        final_run_lock = _build_run_lock(
            run_id=run_id,
            authority=final_authority,
            predecessor=final_predecessor,
            fixture=fixture,
            schedule=schedule,
            project_root=project_root,
            env_file=env_file,
        )
        _assert_run_lock_current(run_lock, final_run_lock)
    except Exception as exc:  # noqa: BLE001 - identity drift is a sealed gate failure
        return {"status": "FAIL", **_error_receipt(exc)}
    return {"status": "PASS", "checked_at": _now()}


def _fixed_fixture_governance_manifest(
    *,
    run_id: str = AUTHORIZED_RUN_ID,
    project_prefix: str = "mvp01-u0-warm",
    fixture: B0RuntimeCase | None = None,
) -> tuple[dict[str, object], ...]:
    fixed_fixture = fixture or build_synthetic_fixture()
    project_id = deterministic_project_id(
        run_id,
        fixed_fixture.case_id,
        prefix=project_prefix,
    )
    subject_id = (
        f"mvp01-warm:{project_id}:subject:"
        f"{sha256_json({'project_id': project_id, 'case_id': fixed_fixture.case_id})[:24]}"
    )
    manifest: list[dict[str, object]] = []
    for event in fixed_fixture.history_events:
        session_id = deterministic_history_session_id(
            event.case_id,
            event.session_ordinal,
            event.original_session_id,
        )
        round_ordinal = event.turn_ordinal // 2
        content = f"{event.role}: {event.content}"
        manifest.append(
            {
                "event_id": event.event_id,
                "source_ref": (
                    f"mvp01-warm://case/{quote(event.case_id, safe='')}/session/"
                    f"{event.session_ordinal}/"
                    f"{quote(event.original_session_id, safe='')}/turn/"
                    f"{event.turn_ordinal}?event_id={event.event_id}"
                ),
                "subject_id": subject_id,
                "speaker": event.role,
                "original_session_id": event.original_session_id,
                "source_event_identity": {
                    "case_id": event.case_id,
                    "event_id": event.event_id,
                    "original_session_id": event.original_session_id,
                    "session_ordinal": event.session_ordinal,
                    "turn_ordinal": event.turn_ordinal,
                },
                "source_context": {
                    "session_id": session_id,
                    "turn_id": f"{session_id}:turn:{event.turn_ordinal}",
                    "turn_ordinal": event.turn_ordinal,
                    "round_id": f"{session_id}:round:{round_ordinal}",
                    "round_ordinal": round_ordinal,
                    "previous_turn_id": (
                        f"{session_id}:turn:{event.turn_ordinal - 1}"
                        if event.turn_ordinal > 0
                        else None
                    ),
                    "next_turn_id": None,
                },
                "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "content_chars": len(content),
            }
        )
    return tuple(manifest)


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


@lru_cache(maxsize=512)
def _frozen_reader_memory_tokens(
    question: str,
    question_at: str,
    reader_context: str,
) -> int:
    return frozen_reader_token_counter().memory_tokens(
        question=question,
        question_as_of=question_at,
        memory_context=reader_context,
    )


@lru_cache(maxsize=4096)
def _frozen_reader_unit_span(
    question: str,
    question_at: str,
    reader_context: str,
    char_start: int,
    char_end: int,
) -> tuple[int, int]:
    return frozen_reader_token_counter().unit_prompt_token_span(
        question=question,
        question_as_of=question_at,
        memory_context=reader_context,
        context_char_start=char_start,
        context_char_end=char_end,
    )


def _validate_receipt_visible_mapping(
    *,
    question: str,
    question_at: str,
    reader_context: str,
    receipt: Mapping[str, object],
    visible: Mapping[str, object],
    selected_ids: Sequence[str],
    selected_refs: Sequence[str],
    governance_pairs: Mapping[str, str],
) -> None:
    receipt_mapping = _require_sequence_of_mappings(
        receipt.get("receipt_mapping"), "archived ContextReceipt mapping"
    )
    rendered_units = _require_sequence_of_mappings(
        visible.get("rendered_units"), "archived Reader rendered units"
    )
    if not receipt_mapping or len(receipt_mapping) != len(rendered_units):
        raise DG14ContractError(
            "archived ContextReceipt differs from Reader rendered units"
        )
    aliases: list[str] = []
    mapped_ids: list[str] = []
    mapped_refs: list[str] = []
    encoded_context = reader_context.encode()
    previous_char_end = -1
    for mapping, rendered in zip(receipt_mapping, rendered_units, strict=True):
        alias = mapping.get("alias")
        mapping_ids = _required_string_list(mapping, "evidence_ids")
        mapping_refs = _required_string_list(mapping, "source_turn_refs")
        if (
            not isinstance(alias, str)
            or len(alias) < 2
            or alias[0] not in "CDEI"
            or not alias[1:].isdigit()
            or int(alias[1:]) <= 0
            or alias in aliases
            or len(mapping_ids) != len(mapping_refs)
            or [governance_pairs.get(value) for value in mapping_ids] != mapping_refs
            or rendered.get("alias") != alias
            or _required_string_list(rendered, "evidence_ids") != mapping_ids
            or _required_string_list(rendered, "source_turn_refs") != mapping_refs
        ):
            raise DG14ContractError(
                "archived ContextReceipt/Reader unit provenance drifted"
            )
        char_offset = _require_mapping(
            rendered.get("serialized_char_offset"),
            "archived Reader character offset",
        )
        byte_offset = _require_mapping(
            rendered.get("serialized_utf8_byte_offset"),
            "archived Reader byte offset",
        )
        char_start = _require_nonnegative_int(
            char_offset.get("start"), "archived Reader character start"
        )
        char_end = _require_nonnegative_int(
            char_offset.get("end"), "archived Reader character end"
        )
        byte_start = _require_nonnegative_int(
            byte_offset.get("start"), "archived Reader byte start"
        )
        byte_end = _require_nonnegative_int(
            byte_offset.get("end"), "archived Reader byte end"
        )
        token_start = _require_nonnegative_int(
            rendered.get("reader_prompt_token_start"),
            "archived Reader prompt token start",
        )
        token_end = _require_nonnegative_int(
            rendered.get("reader_prompt_token_end"),
            "archived Reader prompt token end",
        )
        if (
            char_start <= previous_char_end
            or char_start >= char_end
            or char_end > len(reader_context)
            or byte_start >= byte_end
            or byte_end > len(encoded_context)
            or token_end <= token_start
        ):
            raise DG14ContractError("archived Reader unit offsets are invalid")
        serialized = reader_context[char_start:char_end]
        try:
            byte_serialized = encoded_context[byte_start:byte_end].decode()
            expected_token_span = _frozen_reader_unit_span(
                question,
                question_at,
                reader_context,
                char_start,
                char_end,
            )
        except (FrozenReaderTokenAccountingError, UnicodeDecodeError) as exc:
            raise DG14ContractError(
                "archived Reader byte/token offsets cannot be replayed"
            ) from exc
        header_start = reader_context.rfind(f"[{alias} ", 0, char_start)
        header_end = (
            reader_context.find("\n", header_start) if header_start >= 0 else -1
        )
        if (
            byte_serialized != serialized
            or byte_start != len(reader_context[:char_start].encode())
            or byte_end != len(reader_context[:char_end].encode())
            or (token_start, token_end) != expected_token_span
            or header_start < 0
            or header_end + 1 != char_start
            or rendered.get("serialized_unit_sha256")
            != hashlib.sha256(serialized.encode()).hexdigest()
        ):
            raise DG14ContractError(
                "archived Reader unit is not replayable from Context"
            )
        previous_char_end = char_end
        aliases.append(alias)
        mapped_ids.extend(mapping_ids)
        mapped_refs.extend(mapping_refs)
    if mapped_ids != list(selected_ids) or mapped_refs != list(selected_refs):
        raise DG14ContractError(
            "archived ContextReceipt mapping is not selected-Evidence lossless"
        )


def _request_evidence_archive(
    *,
    request: Mapping[str, str],
    result: Any,
    governance_receipts: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    raw_resolve = _json_safe(result.raw_resolve)
    memory_context = _json_safe(
        _require_mapping(result.raw_resolve.get("memory_context"), "MemoryContext")
    )
    usage = result.usage
    return {
        "schema_version": EVIDENCE_ARCHIVE_SCHEMA,
        "request": {
            "request_id": request["request_id"],
            "query_class": request["query_class"],
            "question": request["question"],
            "question_at": request["question_at"],
            "expected_source_ref_prefix": request["expected_source_ref_prefix"],
        },
        "raw_resolve": raw_resolve,
        "raw_resolve_sha256": _digest(raw_resolve),
        "context_receipt": _json_safe(result.raw_resolve.get("context_receipt")),
        "runtime_memory_context": memory_context,
        "reader_context": result.context,
        "raw_retrieval_trace": _json_safe(usage.get("raw_retrieval_trace")),
        "admitted_evidence_trace": _json_safe(usage.get("admitted_evidence_trace")),
        "reader_visible_trace": _json_safe(usage.get("reader_visible_trace")),
        "selected_evidence_ids": _json_safe(
            _require_mapping(
                result.raw_resolve.get("memory_context"), "MemoryContext"
            ).get("selected_evidence_ids")
        ),
        "selected_source_turn_refs": _json_safe(
            _require_mapping(
                result.raw_resolve.get("memory_context"), "MemoryContext"
            ).get("selected_source_turn_refs")
        ),
        "governance_receipts": _json_safe(governance_receipts),
        "governance_universe_sha256": _digest(_json_safe(governance_receipts)),
        "access_trace": _json_safe(result.raw_resolve.get("access_trace")),
        "mcp_output_compaction": _json_safe(
            result.raw_resolve.get("mcp_output_compaction")
        ),
        # dataclasses.asdict preserves tuple fields.  Normalize the live object
        # before validation so the in-memory and sealed JSON contracts are
        # identical rather than relying on json.dump to change their types.
        "provenance": _json_safe([asdict(item) for item in result.provenance]),
        "result_contract": {
            "status": result.status,
            "declared_tokens": result.declared_tokens,
            "candidate_count": usage.get("candidate_count"),
            "source_ids": list(result.source_ids),
            "selected_source_refs": list(result.selected_source_refs),
            "semantic_context_digest": usage.get("semantic_context_digest"),
            "reader_context_digest": usage.get("reader_context_digest"),
        },
    }


def _validate_request_evidence_archive(
    archive: Mapping[str, object],
    *,
    mcp_response_sha256: object,
    governance_manifest: Sequence[Mapping[str, object]] | None = None,
) -> None:
    if archive.get("schema_version") != EVIDENCE_ARCHIVE_SCHEMA:
        raise DG14ContractError("warm request evidence archive schema drifted")
    raw_resolve = _require_mapping(archive.get("raw_resolve"), "archived resolve")
    memory_context = _require_mapping(
        archive.get("runtime_memory_context"), "archived MemoryContext"
    )
    raw_receipt = archive.get("context_receipt")
    receipt = raw_receipt if isinstance(raw_receipt, Mapping) else None
    visible = _require_mapping(
        archive.get("reader_visible_trace"), "archived Reader-visible trace"
    )
    admitted = _require_mapping(
        archive.get("admitted_evidence_trace"), "archived admitted trace"
    )
    access_trace = _require_mapping(
        archive.get("access_trace"), "archived access trace"
    )
    reader_context = archive.get("reader_context")
    if not isinstance(reader_context, str) or not reader_context:
        raise DG14ContractError("warm archive lacks Reader Context preimage")
    archived_request = _require_mapping(
        archive.get("request"), "archived request identity"
    )
    question = archived_request.get("question")
    question_at = archived_request.get("question_at")
    if (
        not isinstance(question, str)
        or not question
        or not isinstance(question_at, str)
        or not question_at
    ):
        raise DG14ContractError("archived Reader request identity is invalid")
    if raw_resolve.get("memory_context") != memory_context:
        raise DG14ContractError("archived MemoryContext differs from raw resolve")
    if raw_resolve.get("context_receipt") != raw_receipt:
        raise DG14ContractError("archived ContextReceipt differs from raw resolve")
    if raw_resolve.get("access_trace") != access_trace:
        raise DG14ContractError("archived access trace differs from raw resolve")
    span_links = _require_mapping(
        access_trace.get("span_links"), "archived access span links"
    )
    result_contract = _require_mapping(
        archive.get("result_contract"), "archived result contract"
    )
    if (
        not _is_exact_int(access_trace.get("logical_mcp_calls"), 1)
        or not _is_exact_int(access_trace.get("automatic_retry_count"), 0)
        or not _is_exact_int(access_trace.get("retry_policy_max_retries"), 0)
        or not isinstance(span_links.get("runtime_request_id"), str)
        or not span_links.get("runtime_request_id")
        or not isinstance(span_links.get("retrieval_trace_id"), str)
        or not span_links.get("retrieval_trace_id")
    ):
        raise DG14ContractError("archived access trace contract is invalid")
    runtime_status = raw_resolve.get("status")
    if (
        raw_resolve.get("schema_version") != "access-outcome-v0.1"
        or raw_resolve.get("fallback_used") is not False
        or runtime_status
        not in {"HIT", "PARTIAL", "CONTESTED", "ABSENT", "ABSTAINED"}
        or runtime_status != result_contract.get("status")
        or raw_resolve.get("reason") == "MCP_OUTPUT_LIMIT"
        or raw_resolve.get("request_id") != span_links.get("runtime_request_id")
        or raw_resolve.get("trace_id") != span_links.get("retrieval_trace_id")
    ):
        raise DG14ContractError("archived raw MCP terminal identity drifted")
    if archive.get("raw_resolve_sha256") != _digest(raw_resolve):
        raise DG14ContractError("archived raw resolve digest is invalid")
    if mcp_response_sha256 is not None and mcp_response_sha256 != _digest(raw_resolve):
        raise DG14ContractError("MCP response digest lacks an exact archived preimage")
    if memory_context.get("text") != reader_context:
        raise DG14ContractError("archived Reader Context differs from MemoryContext")
    reader_digest = hashlib.sha256(reader_context.encode()).hexdigest()
    semantic_digest = memory_context.get("semantic_context_digest")
    selected_ids = _required_string_list(archive, "selected_evidence_ids")
    selected_refs = _required_string_list(archive, "selected_source_turn_refs")
    raw_items = raw_resolve.get("items")
    raw_evidence_refs = raw_resolve.get("evidence_refs")
    raw_windows = memory_context.get("windows")
    safe_empty_terminal = (
        runtime_status in {"ABSENT", "ABSTAINED"}
        and raw_receipt is None
        and selected_ids == []
        and selected_refs == []
        and raw_items == []
        and raw_evidence_refs == []
        and raw_windows == []
        and _is_exact_int(memory_context.get("selected_windows"), 0)
    )
    evidence_bearing_terminal = bool(selected_ids or selected_refs)
    if receipt is None and not safe_empty_terminal:
        raise DG14ContractError("archived required ContextReceipt is absent")
    if receipt is not None and not evidence_bearing_terminal:
        raise DG14ContractError("archived safe-empty terminal forged a ContextReceipt")
    if (
        memory_context.get("schema_version") != "memory-context-v0.1"
        or visible.get("schema_version") != "reader-visible-trace-v0.1"
        or admitted.get("schema_version") != "admitted-evidence-trace-v0.1"
        or memory_context.get("reader_context_digest") != reader_digest
        or visible.get("reader_context_sha256") != reader_digest
        or result_contract.get("reader_context_digest") != reader_digest
        or not _valid_sha256(semantic_digest)
        or result_contract.get("semantic_context_digest") != semantic_digest
    ):
        raise DG14ContractError("archived semantic/Reader digest chain is invalid")
    if evidence_bearing_terminal and (
        receipt is None
        or receipt.get("reader_context_digest") != reader_digest
        or receipt.get("semantic_context_digest") != semantic_digest
        or receipt.get("schema_version") != "context-receipt-v0.2"
        or memory_context.get("authority_class") != "EVIDENCE_ONLY"
        or receipt.get("authority_class") != "EVIDENCE_ONLY"
        or receipt.get("persisted") is not False
        or receipt.get("canonical_mutation") is not False
    ):
        raise DG14ContractError("archived Evidence ContextReceipt chain is invalid")
    if safe_empty_terminal and memory_context.get("authority_class") != "CANONICAL_STATE":
        raise DG14ContractError("archived safe-empty terminal authority drifted")
    compile_trace = _require_mapping(
        memory_context.get("compile_trace"), "archived Context compile trace"
    )
    if (
        not _is_exact_int(compile_trace.get("hidden_model_calls"), 0)
        or not _is_exact_int(compile_trace.get("atomic_unit_truncation_count"), 0)
        or not _is_exact_int(compile_trace.get("long_turn_split_count"), 0)
        or not _is_exact_int(compile_trace.get("rank_first_prefix_violation_count"), 0)
        or compile_trace.get("whole_unit_admission") is not True
        or visible.get("tokenizer_sha256") != EXPECTED_TOKENIZER_SHA256
        or visible.get("chat_template_sha256") != EXPECTED_CHAT_TEMPLATE_SHA256
    ):
        raise DG14ContractError("archived deterministic Context compile proof drifted")
    parts = visible.get("serialization_parts")
    if (
        not isinstance(parts, list)
        or not all(isinstance(item, str) for item in parts)
        or "\n\n".join(parts) != reader_context
        or visible.get("serialization_replay_sha256") != reader_digest
        or not _is_exact_int(visible.get("reader_call_count"), 0)
    ):
        raise DG14ContractError("archived Reader serialization is not replayable")
    declared_tokens = result_contract.get("declared_tokens")
    estimated_tokens = memory_context.get("estimated_tokens")
    try:
        replayed_reader_tokens = _frozen_reader_memory_tokens(
            question,
            question_at,
            reader_context,
        )
    except FrozenReaderTokenAccountingError as exc:
        raise DG14ContractError("archived Reader tokens cannot be replayed") from exc
    if (
        not isinstance(declared_tokens, int)
        or isinstance(declared_tokens, bool)
        or declared_tokens < 0
        or declared_tokens > EVIDENCE_TOKEN_BUDGET
        or not isinstance(estimated_tokens, int)
        or isinstance(estimated_tokens, bool)
        or estimated_tokens < 0
        or estimated_tokens > EVIDENCE_TOKEN_BUDGET
        or not _is_exact_int(memory_context.get("token_budget"), EVIDENCE_TOKEN_BUDGET)
        or not _is_exact_int(visible.get("exact_reader_memory_tokens"), declared_tokens)
        or declared_tokens != replayed_reader_tokens
    ):
        raise DG14ContractError("archived exact Reader token count drifted")
    compiler_version = compile_trace.get("compiler_version")
    expected_selector_identity = _digest(
        {
            "compiler_version": compiler_version,
            "reader_context_digest": reader_digest,
            "selected_evidence_ids": selected_ids,
        }
    )
    expected_source_ref_prefix = archived_request.get("expected_source_ref_prefix")
    if (
        len(selected_ids) != len(selected_refs)
        or len(set(selected_ids)) != len(selected_ids)
        or len(set(selected_refs)) != len(selected_refs)
        or _required_string_list(memory_context, "selected_evidence_ids")
        != selected_ids
        or _required_string_list(memory_context, "selected_source_turn_refs")
        != selected_refs
        or not isinstance(compiler_version, str)
        or not compiler_version
        or admitted.get("selector_identity") != expected_selector_identity
        or not isinstance(expected_source_ref_prefix, str)
        or not expected_source_ref_prefix
    ):
        raise DG14ContractError("archived selected Evidence identity is invalid")
    if evidence_bearing_terminal and (
        receipt is None
        or _required_string_list(receipt, "source_evidence_ids") != selected_ids
    ):
        raise DG14ContractError("archived ContextReceipt Evidence identity is invalid")
    governance_rows = _require_sequence_of_mappings(
        archive.get("governance_receipts"), "archived governance receipts"
    )
    if archive.get("governance_universe_sha256") != _digest(governance_rows):
        raise DG14ContractError("archived capture governance digest drifted")
    governance_pairs: dict[str, str] = {}
    governance_capture: dict[str, Mapping[str, object]] = {}
    governance_digests: dict[str, str] = {}
    governance_expected: dict[str, Mapping[str, object]] = {}
    seen_refs: set[str] = set()
    seen_events: set[str] = set()
    seen_outboxes: set[str] = set()
    seen_capture_request_ids: set[str] = set()
    capture_subjects: set[str] = set()
    fixture_manifest = tuple(
        governance_manifest
        if governance_manifest is not None
        else _fixed_fixture_governance_manifest()
    )
    if (
        len(governance_rows) != len(fixture_manifest)
        or len(fixture_manifest) != FIXTURE_EVENT_COUNT
    ):
        raise DG14ContractError("archived capture governance denominator drifted")
    for row, expected in zip(governance_rows, fixture_manifest, strict=True):
        event_id = row.get("event_id")
        evidence_id = row.get("evidence_id")
        outbox_id = row.get("outbox_id")
        source_ref = row.get("source_ref")
        capture_request = row.get("capture_request")
        source_event_identity = row.get("source_event_identity")
        confirmation = row.get("confirmation_summary")
        source_context = (
            capture_request.get("source_context")
            if isinstance(capture_request, Mapping)
            else None
        )
        runtime_request_id = (
            confirmation.get("runtime_request_id")
            if isinstance(confirmation, Mapping)
            else None
        )
        if (
            not isinstance(event_id, str)
            or not event_id
            or not isinstance(evidence_id, str)
            or not evidence_id
            or not isinstance(outbox_id, str)
            or not outbox_id
            or not isinstance(source_ref, str)
            or not source_ref
            or not isinstance(capture_request, Mapping)
            or not isinstance(source_event_identity, Mapping)
            or not isinstance(confirmation, Mapping)
            or not isinstance(source_context, Mapping)
            or not isinstance(runtime_request_id, str)
            or not runtime_request_id
            or event_id in seen_events
            or evidence_id in governance_pairs
            or outbox_id in seen_outboxes
            or source_ref in seen_refs
            or runtime_request_id in seen_capture_request_ids
            or event_id != expected.get("event_id")
            or source_ref != expected.get("source_ref")
            or row.get("canonical_changed") is not False
            or capture_request.get("source_type") != "MVP01_SYNTHETIC_WARM_TURN"
            or capture_request.get("source_ref") != source_ref
            or capture_request.get("subject_id") != expected.get("subject_id")
            or capture_request.get("speaker") != expected.get("speaker")
            or capture_request.get("confirmation") != "CAPTURE"
            or capture_request.get("permission_purpose") != "MVP01_U0_WARM_RELIABILITY"
            or capture_request.get("retention_state") != "READABLE"
            or capture_request.get("data_classification") != "SYNTHETIC"
            or dict(source_event_identity) != expected.get("source_event_identity")
            or dict(source_context) != expected.get("source_context")
            or confirmation.get("source_type") != capture_request.get("source_type")
            or confirmation.get("source_ref") != source_ref
            or confirmation.get("subject_id") != capture_request.get("subject_id")
            or confirmation.get("speaker") != capture_request.get("speaker")
            or confirmation.get("structured_source_context") is not True
            or confirmation.get("permission_purpose")
            != capture_request.get("permission_purpose")
            or confirmation.get("retention_state")
            != capture_request.get("retention_state")
            or confirmation.get("data_classification")
            != capture_request.get("data_classification")
            or not isinstance(confirmation.get("content_sha256"), str)
            or confirmation.get("content_sha256") != expected.get("content_sha256")
            or not isinstance(confirmation.get("content_chars"), int)
            or isinstance(confirmation.get("content_chars"), bool)
            or confirmation.get("content_chars") != expected.get("content_chars")
        ):
            raise DG14ContractError("archived governance identity is not unique")
        seen_events.add(event_id)
        governance_pairs[evidence_id] = source_ref
        governance_capture[evidence_id] = capture_request
        governance_expected[evidence_id] = expected
        governance_digests[evidence_id] = _digest(
            {
                "source_event_identity": source_event_identity,
                "capture_request": capture_request,
                "confirmation_summary": confirmation,
            }
        )
        seen_outboxes.add(outbox_id)
        seen_refs.add(source_ref)
        seen_capture_request_ids.add(runtime_request_id)
        capture_subjects.add(str(capture_request["subject_id"]))
    if len(capture_subjects) != 1:
        raise DG14ContractError("archived capture governance denominator drifted")
    if [governance_pairs.get(value) for value in selected_ids] != selected_refs:
        raise DG14ContractError("archived governance provenance is not lossless")
    if evidence_bearing_terminal:
        if receipt is None:  # pragma: no cover - guarded above
            raise DG14ContractError("archived required ContextReceipt is absent")
        _validate_receipt_visible_mapping(
            question=question,
            question_at=question_at,
            reader_context=reader_context,
            receipt=receipt,
            visible=visible,
            selected_ids=selected_ids,
            selected_refs=selected_refs,
            governance_pairs=governance_pairs,
        )
    elif visible.get("rendered_units") != []:
        raise DG14ContractError("safe-empty terminal rendered Evidence units")
    admitted_units = _require_sequence_of_mappings(
        admitted.get("admitted_units"), "archived admitted units"
    )
    admitted_pairs = [
        (row.get("evidence_id"), row.get("source_ref")) for row in admitted_units
    ]
    if admitted_pairs != list(zip(selected_ids, selected_refs, strict=True)):
        raise DG14ContractError(
            "archived admitted trace differs from selected Evidence"
        )
    if not _is_exact_int(admitted.get("atomic_unit_truncation_count"), 0):
        raise DG14ContractError("archived admitted Evidence was atomically truncated")
    raw_trace = archive.get("raw_retrieval_trace")
    if not isinstance(raw_trace, list) or (
        evidence_bearing_terminal and not raw_trace
    ):
        raise DG14ContractError("archived raw retrieval trace is invalid")
    raw_items = _require_sequence_of_mappings(
        raw_resolve.get("items"), "archived raw MCP items"
    )
    if len(raw_items) != len(raw_trace) or not _is_exact_int(
        result_contract.get("candidate_count"), len(raw_trace)
    ):
        raise DG14ContractError("archived candidate denominator drifted")
    raw_ids: set[str] = set()
    raw_refs: set[str] = set()
    raw_id_order: list[str] = []
    provenance_order: list[tuple[int, str]] = []
    provenance_evidence: dict[tuple[int, str], list[str]] = {}
    provenance_refs: dict[tuple[int, str], list[str]] = {}
    provenance_scores: dict[tuple[int, str], list[float]] = {}
    capture_subject = next(iter(capture_subjects))
    for ordinal, (row, raw_item) in enumerate(
        zip(raw_trace, raw_items, strict=True), start=1
    ):
        if not isinstance(row, Mapping):
            raise DG14ContractError("archived raw retrieval row is invalid")
        identity = _require_mapping(
            row.get("evidence_identity"), "archived raw Evidence identity"
        )
        evidence_id = identity.get("evidence_id")
        source_ref = identity.get("source_ref")
        score = row.get("raw_score")
        raw_score = raw_item.get("relevance_score")
        capture_request = governance_capture.get(str(evidence_id))
        raw_expected = governance_expected.get(str(evidence_id))
        raw_expected_event_identity = (
            raw_expected.get("source_event_identity")
            if isinstance(raw_expected, Mapping)
            else None
        )
        source_context = (
            capture_request.get("source_context")
            if isinstance(capture_request, Mapping)
            else None
        )
        if (
            row.get("channel") != "RUNTIME_EVIDENCE_RESOLVE"
            or not _is_exact_int(row.get("channel_rank"), ordinal)
            or (
                score is not None
                and (not isinstance(score, float) or not math.isfinite(score))
            )
            or not isinstance(evidence_id, str)
            or evidence_id in raw_ids
            or not isinstance(source_ref, str)
            or source_ref in raw_refs
            or governance_pairs.get(str(evidence_id)) != source_ref
            or not isinstance(source_context, Mapping)
            or not isinstance(raw_expected, Mapping)
            or not isinstance(raw_expected_event_identity, Mapping)
            or identity.get("subject_id") != raw_expected.get("subject_id")
            or identity.get("original_session_id")
            != raw_expected_event_identity.get("original_session_id")
            or identity.get("source_session_id") != source_context.get("session_id")
            or identity.get("turn_id") != source_context.get("turn_id")
            or not _is_exact_int(
                identity.get("session_ordinal"),
                _require_nonnegative_int(
                    raw_expected_event_identity.get("session_ordinal"),
                    "archived source Event session ordinal",
                ),
            )
            or row.get("capture_governance_sha256")
            != governance_digests.get(str(evidence_id))
            or raw_item.get("kind") != "EVIDENCE_OBSERVATION"
            or raw_item.get("canonical") is not False
            or raw_item.get("evidence_id") != evidence_id
            or raw_item.get("source_ref") != source_ref
            or raw_item.get("subject_id") != capture_subject
            or (score is None) != (raw_score is None)
            or (
                score is not None
                and (
                    isinstance(raw_score, bool)
                    or not isinstance(raw_score, (int, float))
                    or not math.isfinite(float(raw_score))
                    or float(raw_score) != float(score)
                )
            )
        ):
            raise DG14ContractError("archived raw Evidence identity drifted")
        raw_ids.add(evidence_id)
        raw_refs.add(source_ref)
        raw_id_order.append(evidence_id)
        provenance_key = (
            _require_nonnegative_int(
                identity.get("session_ordinal"),
                "archived provenance session ordinal",
            ),
            str(identity["original_session_id"]),
        )
        if provenance_key not in provenance_evidence:
            provenance_order.append(provenance_key)
            provenance_evidence[provenance_key] = []
            provenance_refs[provenance_key] = []
            provenance_scores[provenance_key] = []
        provenance_evidence[provenance_key].append(evidence_id)
        provenance_refs[provenance_key].append(source_ref)
        if score is not None:
            provenance_scores[provenance_key].append(float(score))
    if _required_string_list(raw_resolve, "evidence_refs") != sorted(raw_id_order):
        raise DG14ContractError("archived raw MCP Evidence references drifted")
    raw_memory_windows = memory_context.get("windows")
    if not isinstance(raw_memory_windows, list):
        raise DG14ContractError("archived MemoryContext windows are invalid")
    if (
        not _is_exact_int(
            memory_context.get("selected_windows"), len(raw_memory_windows)
        )
        or not isinstance(memory_context.get("available_windows"), int)
        or isinstance(memory_context.get("available_windows"), bool)
        or int(memory_context["available_windows"]) < len(raw_memory_windows)
    ):
        raise DG14ContractError("archived MemoryContext window count drifted")
    window_ids_seen: set[str] = set()
    flattened_window_ids: list[str] = []
    flattened_window_refs: list[str] = []
    for window in raw_memory_windows:
        window_mapping = _require_mapping(window, "archived MemoryContext window")
        window_id = window_mapping.get("window_id")
        window_ids = _required_string_list(window_mapping, "evidence_ids")
        window_refs = _required_string_list(window_mapping, "source_turn_refs")
        window_session_id = window_mapping.get("session_id")
        captured_contexts = [governance_capture.get(value) for value in window_ids]
        source_contexts = [
            capture.get("source_context") if isinstance(capture, Mapping) else None
            for capture in captured_contexts
        ]
        if (
            not isinstance(window_id, str)
            or not window_id
            or window_id in window_ids_seen
            or not isinstance(window_session_id, str)
            or not window_session_id
            or not window_ids
            or len(set(window_ids)) != len(window_ids)
            or len(set(window_refs)) != len(window_refs)
            or len(window_ids) != len(window_refs)
            or window_mapping.get("truncated") is not False
            or [governance_pairs.get(value) for value in window_ids] != window_refs
            or any(
                not isinstance(source_context, Mapping)
                or source_context.get("session_id") != window_session_id
                for source_context in source_contexts
            )
            or not raw_ids.intersection(window_ids)
        ):
            raise DG14ContractError(
                "archived Context window Evidence/session identity drifted"
            )
        expansions = window_mapping.get("expansions")
        if not isinstance(expansions, list):
            raise DG14ContractError("archived Context window expansions are invalid")
        for expansion in expansions:
            expansion_mapping = _require_mapping(
                expansion, "archived Context expansion"
            )
            source_evidence_id = expansion_mapping.get("source_evidence_id")
            expanded_ids = _required_string_list(
                expansion_mapping, "expanded_evidence_ids"
            )
            if (
                source_evidence_id not in raw_ids
                or source_evidence_id not in window_ids
                or len(set(expanded_ids)) != len(expanded_ids)
                or any(value not in window_ids for value in expanded_ids)
            ):
                raise DG14ContractError(
                    "archived Context expansion lacks raw causality"
                )
        window_ids_seen.add(window_id)
        flattened_window_ids.extend(window_ids)
        flattened_window_refs.extend(window_refs)
    if (
        len(set(flattened_window_ids)) != len(flattened_window_ids)
        or len(set(flattened_window_refs)) != len(flattened_window_refs)
        or not set(flattened_window_ids).issubset(selected_ids)
        or not set(flattened_window_refs).issubset(selected_refs)
    ):
        raise DG14ContractError(
            "archived MemoryContext window provenance escaped selected Evidence"
        )
    receipt_mapping = (
        _require_sequence_of_mappings(
            receipt.get("receipt_mapping"), "archived ContextReceipt mapping"
        )
        if receipt is not None
        else []
    )
    mapped_window_ids = [
        value
        for item in receipt_mapping
        if str(item.get("alias", "")).startswith("E")
        for value in _required_string_list(item, "evidence_ids")
    ]
    mapped_window_refs = [
        value
        for item in receipt_mapping
        if str(item.get("alias", "")).startswith("E")
        for value in _required_string_list(item, "source_turn_refs")
    ]
    if (
        mapped_window_ids != flattened_window_ids
        or mapped_window_refs != flattened_window_refs
    ):
        raise DG14ContractError(
            "archived ContextReceipt E aliases differ from Context windows"
        )
    provenance_rows = _require_sequence_of_mappings(
        archive.get("provenance"), "archived provenance"
    )
    if len(provenance_rows) != len(provenance_order):
        raise DG14ContractError("archived provenance denominator drifted")
    for rank, (provenance_row, provenance_identity) in enumerate(
        zip(provenance_rows, provenance_order, strict=True), start=1
    ):
        session_ordinal, original_session_id = provenance_identity
        evidence_ids = provenance_evidence[provenance_identity]
        source_refs = provenance_refs[provenance_identity]
        scores = provenance_scores[provenance_identity]
        expected_score = max(scores) if scores else None
        actual_score = provenance_row.get("relevance_score")
        expected_source_id = (
            f"mvp01-warm://case/{quote(FIXTURE_CASE_ID, safe='')}/session/"
            f"{session_ordinal}/{quote(original_session_id, safe='')}"
        )
        if (
            not _is_exact_int(provenance_row.get("rank"), rank)
            or provenance_row.get("source_id") != expected_source_id
            or provenance_row.get("session_id") != original_session_id
            or not _is_exact_int(provenance_row.get("session_ordinal"), session_ordinal)
            or _required_string_list(provenance_row, "evidence_ids") != evidence_ids
            or _required_string_list(provenance_row, "source_refs") != source_refs
            or (expected_score is None and actual_score is not None)
            or (
                expected_score is not None
                and (
                    not isinstance(actual_score, float)
                    or not math.isfinite(actual_score)
                    or actual_score != expected_score
                )
            )
            or provenance_row.get("context_selected")
            is not any(value in selected_ids for value in evidence_ids)
            or provenance_row.get("candidate_kind") != "EVIDENCE_OBSERVATION"
            or provenance_row.get("canonical") is not False
        ):
            raise DG14ContractError("archived provenance differs from raw MCP trace")
    expected_source_ids = [identity[1] for identity in provenance_order[:3]]
    if (
        (evidence_bearing_terminal and not provenance_rows)
        or _required_string_list(result_contract, "source_ids") != expected_source_ids
        or _required_string_list(result_contract, "selected_source_refs") != selected_refs
    ):
        raise DG14ContractError(
            "archived result contract differs from selected Evidence"
        )


def _sealed_request_evidence_valid(row: Mapping[str, object]) -> bool:
    archive = row.get("evidence_archive")
    if not isinstance(archive, Mapping):
        return False
    try:
        _validate_request_evidence_archive(
            archive,
            mcp_response_sha256=row.get("mcp_response_sha256"),
        )
    except (DG14ContractError, U0WarmExecutionError, TypeError, ValueError):
        return False
    access_trace = archive.get("access_trace")
    if not isinstance(access_trace, Mapping):
        return False
    span_links = access_trace.get("span_links")
    result_contract = archive.get("result_contract")
    selected_ids = archive.get("selected_evidence_ids")
    if (
        not isinstance(span_links, Mapping)
        or not isinstance(result_contract, Mapping)
        or not isinstance(selected_ids, list)
    ):
        return False
    receipt_requirement = row.get("context_receipt_requirement")
    receipt_digest_valid = (
        row.get("context_receipt_sha256") == _digest(archive.get("context_receipt"))
        if receipt_requirement == "REQUIRED"
        else (
            receipt_requirement == "NOT_APPLICABLE"
            and archive.get("context_receipt") is None
            and row.get("context_receipt_sha256") is None
        )
    )
    return (
        row.get("evidence_archive_validated") is True
        and row.get("evidence_archive_sha256") == _digest(archive)
        and receipt_digest_valid
        and row.get("context_sha256")
        == hashlib.sha256(str(archive.get("reader_context")).encode()).hexdigest()
        and _is_exact_int(row.get("selected_evidence_count"), len(selected_ids))
        and isinstance(result_contract.get("declared_tokens"), int)
        and not isinstance(result_contract.get("declared_tokens"), bool)
        and row.get("declared_tokens") == result_contract.get("declared_tokens")
        and row.get("runtime_status") == result_contract.get("status")
        and row.get("semantic_context_digest")
        == result_contract.get("semantic_context_digest")
        and row.get("reader_context_digest")
        == result_contract.get("reader_context_digest")
        and row.get("fallback_used") is False
        and row.get("mcp_output_limit") is False
        and _is_exact_int(row.get("access_logical_mcp_calls"), 1)
        and row.get("access_logical_mcp_calls") == access_trace.get("logical_mcp_calls")
        and _is_exact_int(row.get("automatic_retry_count"), 0)
        and row.get("automatic_retry_count")
        == access_trace.get("automatic_retry_count")
        and _is_exact_int(row.get("retry_policy_max_retries"), 0)
        and row.get("retry_policy_max_retries")
        == access_trace.get("retry_policy_max_retries")
        and row.get("runtime_request_id") == span_links.get("runtime_request_id")
        and row.get("retrieval_trace_id") == span_links.get("retrieval_trace_id")
        and row.get("access_span_runtime_request_id")
        == span_links.get("runtime_request_id")
        and row.get("access_span_retrieval_trace_id")
        == span_links.get("retrieval_trace_id")
    )


def _retrieval_runtime_manifest(
    *, env_file: Path, project_root: Path, evidence_dense_enabled: bool = True
) -> dict[str, object]:
    dotenv_values = _read_dotenv_scalars(
        env_file,
        {
            "MILAI_EMBEDDING_PROVIDER",
            "MILAI_EMBEDDING_MODEL_ID",
            "MILAI_EMBEDDING_MODEL_PATH",
            "MILAI_EMBEDDING_SOURCE_DIMENSIONS",
            "MILAI_EMBEDDING_PROJECTION_DIMENSIONS",
            "MILAI_EMBEDDING_PREWARM",
            "MILAI_EMBEDDING_MAX_CONCURRENCY",
            "MILAI_RETRIEVAL_RERANKER_PROVIDER",
        },
    )
    values = {key: os.environ.get(key, value) for key, value in dotenv_values.items()}
    for key in (
        "MILAI_EMBEDDING_PROVIDER",
        "MILAI_EMBEDDING_MODEL_ID",
        "MILAI_EMBEDDING_MODEL_PATH",
        "MILAI_EMBEDDING_SOURCE_DIMENSIONS",
        "MILAI_EMBEDDING_PROJECTION_DIMENSIONS",
        "MILAI_EMBEDDING_PREWARM",
        "MILAI_EMBEDDING_MAX_CONCURRENCY",
        "MILAI_RETRIEVAL_RERANKER_PROVIDER",
    ):
        if key in os.environ and key not in values:
            values[key] = os.environ[key]
    provider = values.get("MILAI_EMBEDDING_PROVIDER", "deterministic_hash")
    model_id = values.get("MILAI_EMBEDDING_MODEL_ID", "deterministic-hash-v1")
    source_dimensions = _manifest_int(
        values.get("MILAI_EMBEDDING_SOURCE_DIMENSIONS", "16"),
        "embedding source dimensions",
        minimum=1,
        maximum=8192,
    )
    projection_dimensions = _manifest_int(
        values.get("MILAI_EMBEDDING_PROJECTION_DIMENSIONS", "16"),
        "embedding projection dimensions",
        minimum=16,
        maximum=128,
    )
    if projection_dimensions not in {16, 128}:
        raise U0WarmExecutionError("embedding projection dimensions are invalid")
    prewarm = _manifest_bool(
        values.get("MILAI_EMBEDDING_PREWARM", "true"), "embedding prewarm"
    )
    max_concurrency = _manifest_int(
        values.get("MILAI_EMBEDDING_MAX_CONCURRENCY", "4"),
        "embedding max concurrency",
        minimum=1,
        maximum=64,
    )
    raw_model_path = values.get("MILAI_EMBEDDING_MODEL_PATH")
    model_path = (
        Path(raw_model_path).expanduser()
        if raw_model_path
        else project_root / "runtime/var/models/all-MiniLM-L6-v2"
    )
    if not model_path.is_absolute():
        model_path = (env_file.parent / model_path).resolve()
    model_path = model_path.resolve()
    assets: dict[str, object] = {}
    if provider == "onnx_sentence_transformer":
        for name, relative in (
            ("model_onnx", Path("onnx/model.onnx")),
            ("tokenizer", Path("tokenizer.json")),
        ):
            path = model_path / relative
            if not path.is_file():
                raise U0WarmExecutionError(f"embedding asset is absent: {path}")
            assets[name] = {"path": str(path), "sha256": _sha256_file(path)}
    return {
        "embedding": {
            "provider": provider,
            "model_id": model_id,
            "model_path": str(model_path),
            "source_dimensions": source_dimensions,
            "projection_dimensions": projection_dimensions,
            "prewarm": prewarm,
            "max_concurrency": max_concurrency,
            "assets": assets,
        },
        "reranker": {
            "provider": "none",
            "source_provider_ignored_by_isolated_smoke": values.get(
                "MILAI_RETRIEVAL_RERANKER_PROVIDER", "none"
            ),
        },
        "evidence_dense_enabled": evidence_dense_enabled,
        "configuration_semantics": (
            "source embedding fields inherited; Evidence Dense explicitly enabled; "
            "isolated-smoke reranker remains none"
        ),
        "generation_model_calls": 0,
    }


def _read_dotenv_scalars(path: Path, keys: set[str]) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise U0WarmExecutionError(
            f"runtime environment file is unreadable: {path}"
        ) from exc
    result: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        if key in keys:
            result[key] = raw.strip().strip('"').strip("'")
    return result


def _manifest_int(value: str, label: str, *, minimum: int, maximum: int) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise U0WarmExecutionError(f"{label} is invalid") from exc
    if result < minimum or result > maximum:
        raise U0WarmExecutionError(f"{label} is invalid")
    return result


def _manifest_bool(value: str, label: str) -> bool:
    normalized = value.casefold()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise U0WarmExecutionError(f"{label} is invalid")


def _seal_warm_artifacts(
    *,
    output_root: Path,
    run_id: str,
    run_lock: Mapping[str, object],
    run_lock_sha256: str,
    checkpoint_path: Path,
    fixture: B0RuntimeCase,
    requests: list[dict[str, object]],
    runtime_attempts: list[dict[str, object]],
    runtime_attempt_count: int,
    interruption_count: int,
    resumed_after_crash: bool,
    artifact_seal_resumed: bool,
    lifecycle: Mapping[str, object],
) -> dict[str, object]:
    runtime = _require_mapping(lifecycle.get("runtime"), "lifecycle runtime")
    readiness = _require_mapping(lifecycle.get("readiness"), "lifecycle readiness")
    cleanup = _require_mapping(
        lifecycle.get("namespace_cleanup"), "lifecycle namespace cleanup"
    )
    worker_before_close = _require_mapping(
        lifecycle.get("worker_before_close"), "lifecycle worker status"
    )
    projection = _require_mapping(
        lifecycle.get("projection_metrics"), "lifecycle projection metrics"
    )
    sealed_runtime_cleanup = _require_mapping(
        lifecycle.get("runtime_cleanup"), "lifecycle runtime cleanup"
    )
    runtime_cleanup = dict(sealed_runtime_cleanup)
    runtime_artifact_seal_error: dict[str, object] | None = None
    try:
        runtime_artifact_seal_reverified = _runtime_artifact_files_match(
            output_root=output_root,
            value=runtime_cleanup.get("runtime_artifacts"),
            expected_run_id=run_id,
            expected_database=runtime.get("database"),
            expected_api_pid=runtime.get("api_pid"),
            expected_worker_pid=runtime.get("worker_pid"),
        )
    except Exception as exc:  # noqa: BLE001 - seal must remain terminal
        runtime_artifact_seal_reverified = False
        runtime_artifact_seal_error = _error_receipt(exc)
    runtime_cleanup["runtime_artifact_seal_reverified"] = (
        runtime_artifact_seal_reverified
    )
    if runtime_artifact_seal_error is not None:
        runtime_cleanup["runtime_artifact_seal_error"] = runtime_artifact_seal_error
    transport_cleanup = _require_mapping(
        lifecycle.get("transport_cleanup"), "lifecycle transport cleanup"
    )
    log_cleanup = _require_mapping(
        lifecycle.get("log_cleanup"), "lifecycle log cleanup"
    )
    final_identity_check = _require_mapping(
        lifecycle.get("final_identity_check"), "lifecycle identity check"
    )
    read_after_write_ms = _optional_number(
        lifecycle.get("read_after_write_searchable_ms")
    )
    assessment = assess_warm_gate(
        requests=requests,
        runtime=runtime,
        readiness=readiness,
        cleanup=cleanup,
        worker_before_close=worker_before_close,
        projection=projection,
        runtime_cleanup=runtime_cleanup,
        transport_cleanup=transport_cleanup,
        log_cleanup=log_cleanup,
        read_after_write_ms=read_after_write_ms,
        runtime_attempts=runtime_attempts,
        runtime_attempt_count=runtime_attempt_count,
        interruption_count=interruption_count,
        resumed_after_crash=resumed_after_crash,
        run_lock=run_lock,
        final_identity_check=final_identity_check,
    )
    logical_attempt_count = sum(
        value
        for row in requests
        if isinstance((value := row.get("attempt_count")), int)
        and not isinstance(value, bool)
    )
    known_retry_values = [
        value
        for row in requests
        if row.get("attempt_count") == 1
        for value in (row.get("automatic_retry_count"),)
    ]
    automatic_retry_count: int | None = (
        sum(value for value in known_retry_values if isinstance(value, int))
        if all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in known_retry_values
        )
        else None
    )
    checkpoint_sha256 = _sha256_file(checkpoint_path)
    results: dict[str, object] = {
        "schema_version": "mila-mvp01-u0-warm-results-v0.3",
        "run_id": run_id,
        "scope": SCOPE_IDENTITY,
        "status": "PASS" if assessment["passed"] is True else "FAIL",
        "run_lock_sha256": run_lock_sha256,
        "checkpoint_sha256": checkpoint_sha256,
        "request_count": len(requests),
        "logical_attempt_count": logical_attempt_count,
        "runtime_attempt_count": runtime_attempt_count,
        "interruption_count": interruption_count,
        "resumed_after_crash": resumed_after_crash,
        "artifact_seal_resumed": artifact_seal_resumed,
        "automatic_retry_count": automatic_retry_count,
        "evidence_archive_count": sum(
            isinstance(row.get("evidence_archive"), Mapping) for row in requests
        ),
        "benchmark_case_count": 0,
        "reader_calls": 0,
        "answer_calls": 0,
        "judge_calls": 0,
        "formal_holdout_consumed": False,
        "data_mode": runtime.get("data_mode"),
        "fixture": _fixture_manifest(fixture),
        "ingest_ms": lifecycle.get("ingest_ms"),
        "read_after_write_searchable_ms": read_after_write_ms,
        "readiness": _json_safe(readiness),
        "requests": requests,
        "assessment": assessment,
        "runtime": _json_safe(runtime),
        "runtime_attempts": runtime_attempts,
        "worker_before_close": _json_safe(worker_before_close),
        "projection_metrics": _json_safe(projection),
        "namespace_cleanup": _json_safe(cleanup),
        "runtime_cleanup": _json_safe(runtime_cleanup),
        "transport_cleanup": _json_safe(transport_cleanup),
        "log_cleanup": _json_safe(log_cleanup),
        "final_identity_check": dict(final_identity_check),
        "shared_error": lifecycle.get("shared_error"),
        "cleanup_error": lifecycle.get("cleanup_error"),
        "wall_ms": lifecycle.get("wall_ms"),
        "peak_rss_kib": lifecycle.get("peak_rss_kib"),
    }
    results_path = output_root / "results.json"
    _atomic_json(results_path, results)
    terminal: dict[str, object] = {
        "schema_version": "mila-mvp01-u0-warm-terminal-v0.3",
        "run_id": run_id,
        "status": PASS_STATUS if assessment["passed"] is True else FAIL_STATUS,
        "block_complete": assessment["passed"] is True,
        "goal_complete": False,
        "next_active_scope": (
            "U1_TARGETED_POSITIVE_NEGATIVE_FIXTURES"
            if assessment["passed"] is True
            else "U0_100_REQUEST_WARM_RELIABILITY_REPAIR"
        ),
        "request_count": len(requests),
        "logical_attempt_count": logical_attempt_count,
        "runtime_attempt_count": runtime_attempt_count,
        "interruption_count": interruption_count,
        "artifact_seal_resumed": artifact_seal_resumed,
        "context_terminal_count": assessment["context_terminal_count"],
        "context_terminal_rate": assessment["context_terminal_rate"],
        "evidence_archive_count": results["evidence_archive_count"],
        "reader_answer_judge_calls": 0,
        "formal_holdout_consumed": False,
        "run_lock_sha256": run_lock_sha256,
        "checkpoint_sha256": checkpoint_sha256,
        "results_sha256": _sha256_file(results_path),
        "completed_at": _now(),
    }
    _atomic_json(output_root / "terminal.json", terminal)
    return terminal


def _initialize_warm_output(
    *,
    output_root: Path,
    run_lock: Mapping[str, object],
    run_id: str,
    schedule: Sequence[Mapping[str, str]],
) -> tuple[dict[str, object], str]:
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = output_root.with_name(f".{output_root.name}.initializing-{os.getpid()}")
    staging.mkdir(parents=False, exist_ok=False)
    (staging / "checkpoint").mkdir()
    _atomic_json(staging / "run-lock.json", run_lock)
    run_lock_sha256 = _sha256_file(staging / "run-lock.json")
    checkpoint: dict[str, object] = {
        "schema_version": CHECKPOINT_SCHEMA,
        "run_id": run_id,
        "run_lock_sha256": run_lock_sha256,
        "schedule_sha256": _digest(schedule),
        "phase": "INITIALIZED",
        "requests": [],
        "in_flight": None,
        "runtime_attempt_count": 0,
        "runtime_attempts": [],
        "interruption_count": 0,
        "created_at": _now(),
    }
    _atomic_json(staging / "checkpoint/state.json", checkpoint)
    os.replace(staging, output_root)
    _fsync_directory(output_root.parent)
    return checkpoint, run_lock_sha256


def _checkpoint_resume_flags(
    *,
    output_preexisted: bool,
    phase: object,
    request_count: int,
    runtime_attempt_count: int,
) -> tuple[bool, bool]:
    artifact_seal_resumed = output_preexisted and phase == "LIFECYCLE_TERMINAL"
    runtime_composition_lost = (
        output_preexisted
        and not artifact_seal_resumed
        and bool(request_count or runtime_attempt_count)
    )
    return artifact_seal_resumed, runtime_composition_lost


def _assert_no_owned_orphan(
    *,
    project_root: Path,
    run_id: str,
) -> dict[str, object]:
    journal_root = project_root / "var/mvp01"
    paths = (
        sorted(journal_root.rglob("runtime-ownership.json"))
        if journal_root.is_dir()
        else []
    )
    matched: list[dict[str, object]] = []
    for path in paths:
        journal = _read_json_object(path, "Runtime ownership journal")
        if journal.get("run_id") != run_id:
            continue
        if journal.get("schema_version") != "milai-local-runtime-ownership-v0.1":
            raise U0WarmExecutionError(
                f"unknown Runtime ownership journal schema: {path}"
            )
        database = journal.get("database")
        if (
            not isinstance(database, str)
            or not database.startswith("milai_smoke_dg14_")
            or len(database) > 63
        ):
            raise U0WarmExecutionError("owned Runtime journal has an unsafe database")
        for key in ("api_process", "worker_process"):
            _validate_owned_process_identity(journal.get(key), key)
        status = journal.get("status")
        matched.append(
            {
                "path": str(path.resolve().relative_to(project_root.resolve())),
                "sha256": _sha256_file(path),
                "status": status,
                "database": database,
            }
        )
        if status != "RELEASED":
            raise U0WarmExecutionError(
                "an exact owned Runtime orphan requires operator recovery before launch: "
                f"{path}"
            )
    return {
        "status": "PASS",
        "run_id": run_id,
        "matching_journal_count": len(matched),
        "matching_released_journals": matched,
        "checked_at": _now(),
    }


def _validate_owned_process_identity(value: object, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise U0WarmExecutionError(f"owned {label} identity is invalid")
    pid = value.get("pid")
    start_ticks = value.get("proc_start_ticks")
    cmdline = value.get("cmdline")
    stored_cmdline_sha256 = value.get("cmdline_sha256")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not isinstance(start_ticks, int)
        or isinstance(start_ticks, bool)
        or start_ticks <= 0
        or not isinstance(value.get("executable"), str)
        or not isinstance(value.get("cwd"), str)
        or not isinstance(cmdline, list)
        or not cmdline
        or not all(isinstance(item, str) and item for item in cmdline)
        or not isinstance(stored_cmdline_sha256, str)
    ):
        raise U0WarmExecutionError(f"owned {label} identity is incomplete")
    assert isinstance(cmdline, list)
    encoded_cmdline = (
        b"\0".join(
            item.encode("utf-8", errors="surrogateescape")
            for item in cmdline
            if isinstance(item, str)
        )
        + b"\0"
    )
    if hashlib.sha256(encoded_cmdline).hexdigest() != stored_cmdline_sha256:
        raise U0WarmExecutionError(f"owned {label} command identity drifted")


def _owned_process_identity_matches(
    value: object,
    *,
    expected_pid: object,
    expected_executable: str,
) -> bool:
    """Cross-link a frozen process receipt to the launched Runtime command."""

    if (
        not isinstance(value, Mapping)
        or not isinstance(expected_pid, int)
        or isinstance(expected_pid, bool)
        or expected_pid <= 0
        or not expected_executable
    ):
        return False
    try:
        _validate_owned_process_identity(value, expected_executable)
    except U0WarmExecutionError:
        return False
    if value.get("pid") != expected_pid:
        return False
    executable = value.get("executable")
    cwd = value.get("cwd")
    cmdline = value.get("cmdline")
    if (
        not isinstance(executable, str)
        or not isinstance(cwd, str)
        or not isinstance(cmdline, list)
        or not cmdline
    ):
        return False
    executable_path = Path(executable)
    cwd_path = Path(cwd)
    command_paths = [
        Path(item)
        for item in cmdline
        if isinstance(item, str) and Path(item).name == expected_executable
    ]
    if (
        not executable_path.is_absolute()
        or not cwd_path.is_absolute()
        or cwd_path.name != "runtime"
        or len(command_paths) != 1
        or not command_paths[0].is_absolute()
    ):
        return False
    launcher_path = command_paths[0]
    expected_launcher_path = cwd_path / ".venv" / "bin" / expected_executable
    interpreter_path = Path(cmdline[0])
    try:
        interpreter_identity = interpreter_path.resolve(strict=False)
        executable_identity = executable_path.resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    return (
        launcher_path == expected_launcher_path
        and interpreter_path.is_absolute()
        and interpreter_identity == executable_identity
    )


def _owned_process_absent(value: object) -> bool:
    """Confirm the exact frozen process is absent without trusting PID alone."""

    if not isinstance(value, Mapping):
        return False
    try:
        _validate_owned_process_identity(value, "process")
    except U0WarmExecutionError:
        return False
    pid = value.get("pid")
    expected_start_ticks = value.get("proc_start_ticks")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or not isinstance(expected_start_ticks, int)
        or isinstance(expected_start_ticks, bool)
    ):
        return False
    try:
        stat = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return True
    except OSError:
        return False
    try:
        closing_paren = stat.rfind(")")
        if closing_paren < 0:
            return False
        stat_tail = stat[closing_paren + 2 :].split()
        current_start_ticks = int(stat_tail[19])
    except (ValueError, IndexError):
        return False
    return current_start_ticks != expected_start_ticks


def _validate_checkpoint(
    checkpoint: Mapping[str, object],
    *,
    run_id: str,
    run_lock_sha256: str,
    schedule: Sequence[Mapping[str, str]],
) -> None:
    if (
        checkpoint.get("schema_version") != CHECKPOINT_SCHEMA
        or checkpoint.get("run_id") != run_id
        or checkpoint.get("run_lock_sha256") != run_lock_sha256
        or checkpoint.get("schedule_sha256") != _digest(schedule)
    ):
        raise U0WarmExecutionError("warm checkpoint identity drifted")
    rows = _require_sequence_of_mappings(
        checkpoint.get("requests"), "checkpoint requests"
    )
    if len(rows) > REQUEST_COUNT:
        raise U0WarmExecutionError("warm checkpoint request denominator overflowed")
    for ordinal, row in enumerate(rows, start=1):
        expected = schedule[ordinal - 1]
        if (
            not _is_exact_int(row.get("ordinal"), ordinal)
            or row.get("request_id") != expected["request_id"]
            or row.get("query_class") != expected["query_class"]
            or row.get("question_sha256") != _digest(expected["question"])
            or not isinstance(row.get("terminal_type"), str)
            or not (
                _is_exact_int(row.get("attempt_count"), 0)
                or _is_exact_int(row.get("attempt_count"), 1)
            )
            or row.get("attempt_certainty") not in {"CERTAIN", "UNCERTAIN"}
        ):
            raise U0WarmExecutionError("warm checkpoint request prefix is invalid")
    in_flight = checkpoint.get("in_flight")
    if in_flight is not None:
        if not isinstance(in_flight, Mapping) or len(rows) >= REQUEST_COUNT:
            raise U0WarmExecutionError("warm checkpoint in-flight marker is invalid")
        expected = schedule[len(rows)]
        if (
            not _is_exact_int(in_flight.get("ordinal"), len(rows) + 1)
            or in_flight.get("request_id") != expected["request_id"]
            or in_flight.get("question_sha256") != _digest(expected["question"])
            or not isinstance(in_flight.get("call_cursor"), int)
            or isinstance(in_flight.get("call_cursor"), bool)
            or int(in_flight["call_cursor"]) < 0
        ):
            raise U0WarmExecutionError("warm checkpoint in-flight identity drifted")
    attempts = _require_sequence_of_mappings(
        checkpoint.get("runtime_attempts"), "checkpoint runtime attempts"
    )
    attempt_count = _require_nonnegative_int(
        checkpoint.get("runtime_attempt_count"), "runtime attempt count"
    )
    if len(attempts) != attempt_count:
        raise U0WarmExecutionError("warm checkpoint runtime attempt ledger drifted")
    if rows and attempt_count == 0:
        raise U0WarmExecutionError(
            "warm checkpoint has requests without a Runtime attempt"
        )
    for ordinal, attempt in enumerate(attempts, start=1):
        if not _is_exact_int(attempt.get("attempt"), ordinal) or attempt.get(
            "status"
        ) not in {
            "STARTING",
            "RUNNING",
            "CLOSED",
            "CLOSE_FAILED",
            "INTERRUPTED_OR_CRASHED",
        }:
            raise U0WarmExecutionError("warm checkpoint Runtime attempt is invalid")
    if isinstance(in_flight, Mapping) and (
        attempt_count == 0
        or not _is_exact_int(in_flight.get("runtime_attempt"), attempt_count)
    ):
        raise U0WarmExecutionError("warm checkpoint in-flight Runtime identity drifted")


def _assert_run_lock_current(
    sealed: Mapping[str, object], current: Mapping[str, object]
) -> None:
    sealed_value = dict(sealed)
    current_value = dict(current)
    sealed_value.pop("created_at", None)
    current_value.pop("created_at", None)
    if _canonical(sealed_value) != _canonical(current_value):
        raise U0WarmExecutionError("warm run-lock code, asset, or authority drifted")


def _read_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise U0WarmExecutionError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise U0WarmExecutionError(f"{label} is not an object")
    return value


def _mark_open_runtime_attempt_crashed(attempts: list[dict[str, object]]) -> None:
    if attempts and attempts[-1].get("status") in {"STARTING", "RUNNING"}:
        attempts[-1]["status"] = "INTERRUPTED_OR_CRASHED"
        attempts[-1]["recovered_at"] = _now()


class _SignalGuard:
    def __init__(self) -> None:
        self._previous: dict[int, Any] = {}
        self._request_count = 0
        self._consumed_count = 0
        self._pre_seal_mask: set[int | signal.Signals] | None = None

    def install(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        for signal_value in (signal.SIGINT, signal.SIGTERM):
            self._previous[signal_value] = signal.getsignal(signal_value)
            signal.signal(signal_value, self._handle)

    def _handle(self, _signal_value: int, _frame: object) -> None:
        self._request_count += 1

    def raise_if_requested(self) -> None:
        if self._request_count > self._consumed_count:
            raise U0WarmInterruption("SIGINT_OR_SIGTERM_REQUESTED")

    def consume_requests(self) -> int:
        pending = self._request_count - self._consumed_count
        self._consumed_count = self._request_count
        return pending

    def begin_seal(self) -> tuple[int, dict[str, object]]:
        """Linearize the terminal commit against SIGINT/SIGTERM delivery."""

        signal_values = {signal.SIGINT, signal.SIGTERM}
        if not self._previous:
            pending = self.consume_requests()
            return pending, {
                "status": "NOT_INSTALLED_NON_MAIN_THREAD",
                "precommit_interruption_count": pending,
            }
        if self._pre_seal_mask is not None:
            raise U0WarmExecutionError("signal seal barrier was already entered")
        old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, signal_values)
        self._pre_seal_mask = set(old_mask)
        delivered = self.consume_requests()
        kernel_pending = set(signal.sigpending()).intersection(signal_values)
        # Drain only the signals observed at the barrier.  Later arrivals remain
        # blocked and are, by definition, post-commit notifications.
        for signal_value in sorted(kernel_pending, key=int):
            signal.sigwait({signal_value})
        precommit_count = delivered + len(kernel_pending)
        return precommit_count, {
            "status": "SEALED",
            "commit_point": "AFTER_CLEANUP_AND_FINAL_IDENTITY_BEFORE_TERMINAL_RENAME",
            "delivered_request_count": delivered,
            "kernel_pending_signals": [
                signal_value.name for signal_value in sorted(kernel_pending, key=int)
            ],
            "precommit_interruption_count": precommit_count,
            "sealed_at": _now(),
        }

    def restore(self) -> None:
        if self._pre_seal_mask is not None:
            # Keep our non-raising handler installed while unblocking.  Any
            # post-commit pending notification is absorbed before the previous
            # process-level policy is restored.
            signal.pthread_sigmask(signal.SIG_SETMASK, self._pre_seal_mask)
            self._pre_seal_mask = None
        for signal_value, previous in self._previous.items():
            signal.signal(signal_value, previous)
        self._previous = {}


def _require_sequence_of_mappings(
    value: object, label: str
) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise U0WarmExecutionError(f"{label} is invalid")
    return value


def _required_string_list(value: Mapping[str, object], key: str) -> list[str]:
    raw = value.get(key)
    if not isinstance(raw, list) or not all(
        isinstance(item, str) and item for item in raw
    ):
        raise DG14ContractError(f"archive lacks valid {key}")
    return raw


def _require_nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise U0WarmExecutionError(f"{label} is invalid")
    return value


def _require_positive_int(value: object, label: str) -> int:
    result = _require_nonnegative_int(value, label)
    if result == 0:
        raise U0WarmExecutionError(f"{label} is invalid")
    return result


def _is_exact_int(value: object, expected: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


def _context_truth_metrics_exact(value: object) -> bool:
    if not isinstance(value, Mapping) or set(value) != set(EXPECTED_METRICS):
        return False
    for name, expected in EXPECTED_METRICS.items():
        actual = value.get(name)
        if isinstance(expected, float):
            if (
                not isinstance(actual, float)
                or not math.isfinite(actual)
                or actual != expected
            ):
                return False
        elif not _is_exact_int(actual, expected):
            return False
    return True


def _optional_number(value: object) -> float | None:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ):
        return float(value)
    return None


def _nonnegative_number_at_most(value: object, maximum: float) -> bool:
    sample = _optional_number(value)
    return sample is not None and 0.0 <= sample <= maximum


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _is_mcp_output_limit(error: BaseException) -> bool:
    return "MCP_OUTPUT_LIMIT" in str(error)


def _failure_class(error: BaseException) -> str:
    if isinstance(error, (ConnectionError, OSError, TimeoutError)):
        return "INFRASTRUCTURE"
    return "PROTOCOL_IMPLEMENTATION"


def _capture_outcome_manifest(
    adapter: DG15MilaiMcpAdapter | None,
) -> dict[str, object]:
    if adapter is None:
        return {"status": "NOT_CREATED", "capture_record_count": 0}
    try:
        records = [
            {
                "sequence": record.sequence,
                "physical_batch_sequence": record.physical_batch_sequence,
                "request_sha256": record.request_sha256,
                "response_sha256": record.response_sha256,
                "status": record.status,
                "error_code": record.error_code,
                "runtime_request_id": record.runtime_request_id,
            }
            for record in adapter.export_call_records()
            if record.stage == "ingest" and record.tool_name == "milai_evidence_capture"
        ]
        stages = [
            asdict(stage)
            for stage in adapter.export_stage_trace()
            if stage.stage == "ingest"
        ]
    except Exception as exc:  # noqa: BLE001 - diagnostic must fail closed
        return _failed_capture_outcome_manifest(exc)
    payload = {
        "status": "OBSERVED",
        "capture_record_count": len(records),
        "succeeded_record_count": sum(
            record["status"] == "SUCCEEDED" for record in records
        ),
        "failed_record_count": sum(record["status"] == "FAILED" for record in records),
        "records_sha256": _digest(records),
        "stage_records_sha256": _digest(stages),
        "records": records,
        "stage_records": stages,
    }
    return {**payload, "manifest_sha256": _digest(payload)}


def _runtime_artifact_manifest(
    *,
    runtime_root: Path,
    output_root: Path,
    mcp_log_path: Path,
    run_id: str,
) -> dict[str, object]:
    expected = {
        "mcp_log": mcp_log_path,
        "runtime_log": runtime_root / "runtime.log",
        "runtime_ownership": runtime_root / "runtime-ownership.json",
    }
    files: dict[str, dict[str, object]] = {}
    errors: list[dict[str, object]] = []
    try:
        resolved_output_root = output_root.resolve()
    except Exception as exc:  # noqa: BLE001 - diagnostic must fail closed
        resolved_output_root = None
        errors.append(
            {
                "component": "output_root",
                "operation": "resolve",
                **_error_receipt(exc),
            }
        )
    for name, path in expected.items():
        entry: dict[str, object] = {"path": None, "present": False}
        try:
            if resolved_output_root is None:
                raise U0WarmExecutionError("Runtime artifact output root is unresolved")
            entry["path"] = str(path.resolve().relative_to(resolved_output_root))
        except Exception as exc:  # noqa: BLE001 - diagnostic must fail closed
            error = {
                "component": name,
                "operation": "relative_path",
                **_error_receipt(exc),
            }
            entry["error"] = error
            errors.append(error)
            files[name] = entry
            continue
        try:
            present = path.is_file()
            entry["present"] = present
        except Exception as exc:  # noqa: BLE001 - diagnostic must fail closed
            error = {
                "component": name,
                "operation": "is_file",
                **_error_receipt(exc),
            }
            entry["error"] = error
            errors.append(error)
            files[name] = entry
            continue
        if present:
            try:
                entry["size_bytes"] = path.stat().st_size
            except Exception as exc:  # noqa: BLE001 - diagnostic must fail closed
                error = {
                    "component": name,
                    "operation": "stat",
                    **_error_receipt(exc),
                }
                entry["error"] = error
                errors.append(error)
            try:
                entry["sha256"] = _sha256_file(path)
            except Exception as exc:  # noqa: BLE001 - diagnostic must fail closed
                error = {
                    "component": name,
                    "operation": "sha256",
                    **_error_receipt(exc),
                }
                entry["error"] = error
                errors.append(error)
        files[name] = entry
    ownership: dict[str, object] = {"status": "UNAVAILABLE"}
    ownership_path = expected["runtime_ownership"]
    try:
        ownership_present = ownership_path.is_file()
    except Exception as exc:  # noqa: BLE001 - diagnostic must fail closed
        ownership_present = False
        errors.append(
            {
                "component": "runtime_ownership",
                "operation": "ownership_is_file",
                **_error_receipt(exc),
            }
        )
    if ownership_present:
        try:
            raw_ownership = _read_json_object(
                ownership_path,
                "Runtime ownership artifact",
            )
        except Exception as exc:  # noqa: BLE001 - preserve a typed manifest failure
            ownership = _error_receipt(exc)
            errors.append(
                {
                    "component": "runtime_ownership",
                    "operation": "read",
                    **_error_receipt(exc),
                }
            )
        else:
            ownership = {
                "schema_version": raw_ownership.get("schema_version"),
                "run_id": raw_ownership.get("run_id"),
                "status": raw_ownership.get("status"),
                "database": raw_ownership.get("database"),
                "api_process": _json_safe(raw_ownership.get("api_process")),
                "worker_process": _json_safe(raw_ownership.get("worker_process")),
            }
    all_files_present = all(entry.get("present") is True for entry in files.values())
    ownership_released = (
        ownership.get("schema_version") == "milai-local-runtime-ownership-v0.1"
        and ownership.get("run_id") == run_id
        and ownership.get("status") == "RELEASED"
    )
    api_process = ownership.get("api_process")
    worker_process = ownership.get("worker_process")
    ownership_processes_recorded = (
        isinstance(api_process, Mapping)
        and _owned_process_identity_matches(
            api_process,
            expected_pid=api_process.get("pid"),
            expected_executable="milai-api",
        )
        and isinstance(worker_process, Mapping)
        and _owned_process_identity_matches(
            worker_process,
            expected_pid=worker_process.get("pid"),
            expected_executable="milai-worker",
        )
    )
    try:
        if resolved_output_root is None:
            raise U0WarmExecutionError("Runtime artifact output root is unresolved")
        relative_runtime_root: str | None = str(
            runtime_root.resolve().relative_to(resolved_output_root)
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic must fail closed
        relative_runtime_root = None
        errors.append(
            {
                "component": "runtime_root",
                "operation": "relative_path",
                **_error_receipt(exc),
            }
        )
    payload = {
        "status": (
            "PASS"
            if all_files_present
            and ownership_released
            and ownership_processes_recorded
            and not errors
            else "FAIL"
        ),
        "runtime_root": relative_runtime_root,
        "files": files,
        "ownership": ownership,
        "all_files_present": all_files_present,
        "ownership_released": ownership_released,
        "ownership_processes_recorded": ownership_processes_recorded,
        "diagnostic_errors": errors,
    }
    return {**payload, "manifest_sha256": _digest(payload)}


def _failed_capture_outcome_manifest(error: BaseException) -> dict[str, object]:
    records: list[object] = []
    stages: list[object] = []
    payload: dict[str, object] = {
        "status": "FAIL",
        "capture_record_count": 0,
        "succeeded_record_count": 0,
        "failed_record_count": 0,
        "records_sha256": _digest(records),
        "stage_records_sha256": _digest(stages),
        "records": records,
        "stage_records": stages,
        "diagnostic_error": _error_receipt(error),
    }
    return {**payload, "manifest_sha256": _digest(payload)}


def _failed_runtime_artifact_manifest(error: BaseException) -> dict[str, object]:
    diagnostic_error = _error_receipt(error)
    payload: dict[str, object] = {
        "status": "FAIL",
        "runtime_root": None,
        "files": {},
        "ownership": {"status": "UNAVAILABLE"},
        "all_files_present": False,
        "ownership_released": False,
        "ownership_processes_recorded": False,
        "diagnostic_errors": [diagnostic_error],
    }
    return {**payload, "manifest_sha256": _digest(payload)}


def _collect_terminal_diagnostic_manifests(
    *,
    adapter: DG15MilaiMcpAdapter | None,
    runtime_root: Path,
    output_root: Path,
    mcp_log_path: Path,
    run_id: str,
) -> tuple[dict[str, object], dict[str, object], tuple[dict[str, object], ...]]:
    """Collect diagnostics without allowing them to create a terminal gap."""

    try:
        capture = _capture_outcome_manifest(adapter)
    except Exception as exc:  # noqa: BLE001 - terminal sealing must continue
        capture = _failed_capture_outcome_manifest(exc)
    try:
        artifacts = _runtime_artifact_manifest(
            runtime_root=runtime_root,
            output_root=output_root,
            mcp_log_path=mcp_log_path,
            run_id=run_id,
        )
    except Exception as exc:  # noqa: BLE001 - terminal sealing must continue
        artifacts = _failed_runtime_artifact_manifest(exc)

    errors: list[dict[str, object]] = []
    capture_error = capture.get("diagnostic_error")
    if isinstance(capture_error, Mapping):
        errors.append({"component": "capture_outcome_summary", **capture_error})
    artifact_errors = artifacts.get("diagnostic_errors")
    if isinstance(artifact_errors, list):
        errors.extend(
            {"manifest": "runtime_artifacts", **dict(error)}
            for error in artifact_errors
            if isinstance(error, Mapping)
        )
    return capture, artifacts, tuple(errors)


def _runtime_artifact_files_match(
    *,
    output_root: Path,
    value: object,
    expected_run_id: object,
    expected_database: object,
    expected_api_pid: object,
    expected_worker_pid: object,
) -> bool:
    """Re-read fixed Runtime artifacts at the final artifact-seal point."""

    try:
        if not _valid_runtime_artifact_manifest(
            value,
            expected_run_id=expected_run_id,
            expected_database=expected_database,
            expected_api_pid=expected_api_pid,
            expected_worker_pid=expected_worker_pid,
        ):
            return False
        if (
            not isinstance(value, Mapping)
            or not isinstance(expected_run_id, str)
            or not isinstance(expected_database, str)
            or not isinstance(expected_api_pid, int)
            or isinstance(expected_api_pid, bool)
            or not isinstance(expected_worker_pid, int)
            or isinstance(expected_worker_pid, bool)
        ):
            return False
        files = value.get("files")
        manifest_ownership = value.get("ownership")
        if not isinstance(files, Mapping) or not isinstance(
            manifest_ownership, Mapping
        ):
            return False
        expected_paths = {
            "mcp_log": output_root / "runtime/attempt-001/mcp-attempt-1.log",
            "runtime_log": output_root / "runtime/attempt-001/runtime.log",
            "runtime_ownership": (
                output_root / "runtime/attempt-001/runtime-ownership.json"
            ),
        }
        for name, path in expected_paths.items():
            entry = files.get(name)
            if (
                not isinstance(entry, Mapping)
                or not path.is_file()
                or path.stat().st_size != entry.get("size_bytes")
                or _sha256_file(path) != entry.get("sha256")
            ):
                return False
        ownership = _read_json_object(
            expected_paths["runtime_ownership"],
            "Runtime ownership artifact at seal",
        )
        return (
            ownership.get("schema_version") == "milai-local-runtime-ownership-v0.1"
            and ownership.get("run_id") == expected_run_id
            and ownership.get("status") == "RELEASED"
            and ownership.get("database") == expected_database
            and ownership.get("api_process") == manifest_ownership.get("api_process")
            and ownership.get("worker_process")
            == manifest_ownership.get("worker_process")
            and _owned_process_identity_matches(
                ownership.get("api_process"),
                expected_pid=expected_api_pid,
                expected_executable="milai-api",
            )
            and _owned_process_identity_matches(
                ownership.get("worker_process"),
                expected_pid=expected_worker_pid,
                expected_executable="milai-worker",
            )
            and _owned_process_absent(ownership.get("api_process"))
            and _owned_process_absent(ownership.get("worker_process"))
        )
    except Exception:  # noqa: BLE001 - verification is deliberately fail closed
        return False


def _error_receipt(error: BaseException) -> dict[str, object]:
    message = str(error)
    return {
        "failure_class": _failure_class(error),
        "error_type": type(error).__name__,
        "message_sha256": hashlib.sha256(message.encode()).hexdigest(),
        "message_excerpt": message[:300],
    }


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DG14ContractError(f"{label} is absent")
    return value


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    return str(value)


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _rounded_number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 6)
    return None


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        temporary.chmod(0o600)
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "FAIL_STATUS",
    "FIXTURE_CASE_ID",
    "FIXTURE_EVENT_COUNT",
    "MAX_QUERY_LATENCY_MS",
    "PASS_STATUS",
    "WARM_MEMORY_CONTROL_P95_MS",
    "U0WarmExecutionError",
    "assess_warm_gate",
    "build_request_schedule",
    "build_synthetic_fixture",
    "nearest_rank_percentile",
    "run_u0_warm_soak",
]
