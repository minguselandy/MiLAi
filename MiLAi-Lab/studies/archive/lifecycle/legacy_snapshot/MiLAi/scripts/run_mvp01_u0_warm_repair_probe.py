#!/usr/bin/env python3
"""Run the one-shot 20-event/10-class MVP-01 U0 warm-002 repair probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg14.benchmark import (
    DEFAULT_CHAT_TEMPLATE,
    DEFAULT_ENV_FILE,
    DEFAULT_TOKENIZER,
    _atomic_json,
    _local_token_counter,
    _process_identity,
)
from evals.dg15.mcp_stdio import MultiplexedStdioMcpTransport
from evals.dg15.milai_mcp_adapter import DG15MilaiMcpAdapter
from evals.dg15.runtime_session import LocalDG15RuntimeSession
from evals.mvp01.u0_warm import (
    EXPECTED_PROJECTION_TERMINAL_WATERMARK,
    _assert_no_owned_orphan,
    _capture_outcome_manifest,
    _execute_request,
    _fixed_fixture_governance_manifest,
    _projection_terminal,
    _retrieval_runtime_manifest,
    _wait_for_namespace_cleanup,
    build_request_schedule,
    build_synthetic_fixture,
)
from evals.mvp01.u0_warm_repair_contract import (
    AUTHORIZED_RUN_ID,
    AUTHORIZED_RUN_LOCK,
    EVIDENCE_TOKEN_BUDGET,
    FIXTURE_EVENT_COUNT,
    QUERY_CLASS_COUNT,
    SCOPE_IDENTITY,
    RepairProbeAuthorityReceipt,
    assert_failed_warm_002,
    assert_repair_probe_authorized,
)

MASTER_PATH = ROOT / "MiLAi_Memory_Lifecycle_总_GOALS.md"
GOAL_PATH = ROOT / "MiLAi_MVP-01_高效可用Memory最小闭环_GOALS.md"
DEFAULT_OUTPUT_ROOT = ROOT / f"var/mvp01/{AUTHORIZED_RUN_ID}"
PROJECT_PREFIX = "mvp01-u0-warm-repair-probe"
PASS_STATUS = "PASS_MVP01_U0_WARM_002_10_CLASS_REPAIR_PROBE"
FAIL_STATUS = "FAIL_MVP01_U0_WARM_002_10_CLASS_REPAIR_PROBE"
CODE_PATHS = (
    "evals/dg14/benchmark.py",
    "evals/dg15/milai_mcp_adapter.py",
    "evals/dg15/runtime_session.py",
    "evals/gdpm/b0_canary_runtime.py",
    "evals/mvp01/u0_warm.py",
    "evals/mvp01/u0_warm_repair_contract.py",
    "runtime/src/milai/application/memory_context.py",
    "scripts/run_mvp01_u0_warm_repair_probe.py",
)


class RepairProbeError(RuntimeError):
    """The bounded repair probe failed its execution or sealing contract."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_value(item) for item in value]
    return str(value)


def _error_receipt(error: BaseException) -> dict[str, object]:
    message = str(error)
    return {
        "error_type": type(error).__name__,
        "message_excerpt": message[:512],
        "message_sha256": hashlib.sha256(message.encode()).hexdigest(),
    }


def _probe_schedule() -> tuple[dict[str, str], ...]:
    schedule = tuple(
        {
            **row,
            "request_id": f"repair-probe-request-{ordinal:03d}",
        }
        for ordinal, row in enumerate(build_request_schedule()[:QUERY_CLASS_COUNT], start=1)
    )
    if (
        len(schedule) != QUERY_CLASS_COUNT
        or len({row["request_id"] for row in schedule}) != QUERY_CLASS_COUNT
        or len({row["query_class"] for row in schedule}) != QUERY_CLASS_COUNT
    ):
        raise RepairProbeError("repair-probe query-class schedule drifted")
    return schedule


def _build_run_lock(
    *,
    authority: RepairProbeAuthorityReceipt,
    predecessor: Mapping[str, object],
    schedule: Sequence[Mapping[str, str]],
) -> dict[str, object]:
    fixture = build_synthetic_fixture()
    events = [event.canonical() for event in fixture.history_events]
    code_artifacts = {
        path: {"path": path, "sha256": _sha256_file(ROOT / path)}
        for path in CODE_PATHS
    }
    request_rows = [
        {
            "ordinal": ordinal,
            "request_id": row["request_id"],
            "query_class": row["query_class"],
            "question_sha256": _digest(row["question"]),
            "question_at": row["question_at"],
            "expected_source_ref_prefix": row["expected_source_ref_prefix"],
            "expected_anchor_required": True,
        }
        for ordinal, row in enumerate(schedule, start=1)
    ]
    retrieval = _retrieval_runtime_manifest(
        env_file=DEFAULT_ENV_FILE,
        project_root=ROOT,
        evidence_dense_enabled=True,
    )
    material: dict[str, object] = {
        "schema_version": "mila-mvp01-u0-warm-repair-probe-run-lock-v0.2",
        "run_id": AUTHORIZED_RUN_ID,
        "created_at": _now(),
        "authority": asdict(authority),
        "predecessor": dict(predecessor),
        "scope": {
            "identity": SCOPE_IDENTITY,
            "synthetic_only": True,
            "fixture_event_count": FIXTURE_EVENT_COUNT,
            "query_class_count": QUERY_CLASS_COUNT,
            "requests_per_query_class": 1,
            "evidence_token_budget": EVIDENCE_TOKEN_BUDGET,
            "automatic_retry_count": 0,
            "benchmark_case_count": 0,
            "reader_calls": 0,
            "answer_calls": 0,
            "judge_calls": 0,
            "formal_holdout_authorized": False,
            "formal_warm_successor_authorized": False,
        },
        "fixture": {
            "case_id": fixture.case_id,
            "event_count": len(events),
            "events_sha256": _digest(events),
        },
        "request_schedule": {
            "request_count": len(request_rows),
            "requests_sha256": _digest(request_rows),
            "requests": request_rows,
        },
        "retrieval_runtime": retrieval,
        "reader_accounting": {
            "tokenizer": {
                "path": str(DEFAULT_TOKENIZER),
                "sha256": _sha256_file(DEFAULT_TOKENIZER),
            },
            "chat_template": {
                "path": str(DEFAULT_CHAT_TEMPLATE),
                "sha256": _sha256_file(DEFAULT_CHAT_TEMPLATE),
            },
        },
        "authority_documents": {
            "master": {
                "path": str(MASTER_PATH.relative_to(ROOT)),
                "sha256": authority.master_sha256,
            },
            "goal": {
                "path": str(GOAL_PATH.relative_to(ROOT)),
                "sha256": authority.goal_sha256,
            },
        },
        "code_artifacts": code_artifacts,
    }
    return {**material, "run_lock_digest": _digest(material)}


def _run_lock_identity_check(run_lock: Mapping[str, object]) -> Mapping[str, object]:
    try:
        authority = assert_repair_probe_authorized(
            master_path=MASTER_PATH,
            goal_path=GOAL_PATH,
        )
        assert_failed_warm_002(ROOT)
        authority_docs = run_lock.get("authority_documents")
        code_artifacts = run_lock.get("code_artifacts")
        if not isinstance(authority_docs, Mapping) or not isinstance(
            code_artifacts, Mapping
        ):
            raise RepairProbeError("run-lock identity manifests are absent")
        master = authority_docs.get("master")
        goal = authority_docs.get("goal")
        if (
            not isinstance(master, Mapping)
            or not isinstance(goal, Mapping)
            or master.get("sha256") != authority.master_sha256
            or goal.get("sha256") != authority.goal_sha256
        ):
            raise RepairProbeError("authority document identity drifted")
        for relative_path, artifact in code_artifacts.items():
            if (
                not isinstance(relative_path, str)
                or not isinstance(artifact, Mapping)
                or artifact.get("path") != relative_path
                or artifact.get("sha256") != _sha256_file(ROOT / relative_path)
            ):
                raise RepairProbeError(f"code identity drifted: {relative_path}")
    except Exception as exc:  # noqa: BLE001 - sealed identity failure
        return {"status": "FAIL", **_error_receipt(exc)}
    return {"status": "PASS", "checked_at": _now()}


def _exact_process_absent(identity: object) -> bool:
    if not isinstance(identity, Mapping):
        return False
    pid = identity.get("pid")
    expected_ticks = identity.get("proc_start_ticks")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not isinstance(expected_ticks, int)
        or isinstance(expected_ticks, bool)
        or expected_ticks <= 0
    ):
        return False
    try:
        current = _process_identity(pid)
    except (OSError, RuntimeError):
        return True
    return current.get("proc_start_ticks") != expected_ticks


def _port_closed(base_url: object) -> bool:
    if not isinstance(base_url, str):
        return False
    parsed = urlsplit(base_url)
    if parsed.hostname is None or parsed.port is None:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((parsed.hostname, parsed.port)) != 0


def _close_transport(
    transport: MultiplexedStdioMcpTransport | None,
    errors: list[dict[str, object]],
) -> None:
    if transport is None:
        return
    try:
        transport.close()
    except Exception as exc:  # noqa: BLE001 - sealed cleanup evidence
        errors.append({"component": "mcp_transport", **_error_receipt(exc)})


def run_probe(*, run_id: str, output_root: Path) -> dict[str, object]:
    """Execute the exact authorized one-shot repair probe and seal its terminal."""

    authority = assert_repair_probe_authorized(
        master_path=MASTER_PATH,
        goal_path=GOAL_PATH,
    )
    predecessor = assert_failed_warm_002(ROOT)
    expected_output_root = (ROOT / AUTHORIZED_RUN_LOCK).parent
    if run_id != AUTHORIZED_RUN_ID:
        raise RepairProbeError(f"repair-probe run id drifted: {run_id}")
    if output_root.resolve() != expected_output_root.resolve():
        raise RepairProbeError(
            f"repair-probe output root drifted: expected {expected_output_root}"
        )
    if output_root.exists():
        raise RepairProbeError("repair-probe output already exists; replay is forbidden")
    schedule = _probe_schedule()
    fixture = build_synthetic_fixture()
    if len(fixture.history_events) != FIXTURE_EVENT_COUNT:
        raise RepairProbeError("repair-probe fixture denominator drifted")
    orphan_preflight = _assert_no_owned_orphan(project_root=ROOT, run_id=run_id)
    run_lock = _build_run_lock(
        authority=authority,
        predecessor=predecessor,
        schedule=schedule,
    )
    output_root.mkdir(parents=True)
    run_lock_path = output_root / "run-lock.json"
    _atomic_json(run_lock_path, run_lock)
    run_lock_sha256 = _sha256_file(run_lock_path)

    runtime_root = output_root / "runtime/attempt-001"
    mcp_log_path = runtime_root / "mcp.log"
    session = LocalDG15RuntimeSession(
        output_root=runtime_root,
        env_file=DEFAULT_ENV_FILE,
        project_root=ROOT,
        mcp_concurrency=4,
        projection_batch_size=16,
        inherit_source_embedding_runtime=True,
        barrier_timeout_ms=120_000,
        data_mode="SYNTHETIC_ONLY",
        memory_formation_mode="OFF",
        progressive_context_evidence=True,
        budget_invariant_context=True,
        retrieval_evidence_dense_enabled=True,
    )
    runtime: Mapping[str, object] = {"status": "NOT_STARTED"}
    readiness: Mapping[str, object] = {"status": "NOT_STARTED"}
    namespace_cleanup: Mapping[str, object] = {"status": "NOT_STARTED"}
    worker_before_close: Mapping[str, object] = {"status": "NOT_STARTED"}
    projection: Mapping[str, object] = {"status": "NOT_COLLECTED"}
    runtime_cleanup: Mapping[str, object] = {"status": "NOT_CREATED"}
    ownership_before: Mapping[str, object] = {}
    ownership_after: Mapping[str, object] = {}
    capture_manifest: Mapping[str, object] = {"status": "NOT_CREATED"}
    requests: list[dict[str, object]] = []
    call_records: list[dict[str, object]] = []
    primary_error: dict[str, object] | None = None
    cleanup_errors: list[dict[str, object]] = []
    transport: MultiplexedStdioMcpTransport | None = None
    adapter: DG15MilaiMcpAdapter | None = None
    adapter_cleaned = False
    mcp_log: BinaryIO | None = None
    try:
        runtime = dict(session.start(run_id))
        ownership_before = json.loads(
            (runtime_root / "runtime-ownership.json").read_text(encoding="utf-8")
        )
        counter = _local_token_counter(DEFAULT_TOKENIZER)
        config = replace(
            session.adapter_config(),
            max_limit=12,
            allowed_budgets=(EVIDENCE_TOKEN_BUDGET,),
            project_prefix=PROJECT_PREFIX,
            barrier_timeout_ms=120_000,
            max_latency_ms=2_000,
            capture_profile="MVP01_SYNTHETIC_WARM",
        )
        mcp_log = mcp_log_path.open("ab")
        transport = MultiplexedStdioMcpTransport(config.dg14_config(), stderr=mcp_log)
        adapter = DG15MilaiMcpAdapter(
            config,
            token_counter=counter,
            transport=transport,
            close_transport_on_cleanup=False,
        )
        adapter.reset(run_id, fixture.case_id)
        adapter.ingest_many(fixture.history_events)
        readiness = dict(adapter.finalize())
        governance_manifest = _fixed_fixture_governance_manifest(
            run_id=run_id,
            project_prefix=PROJECT_PREFIX,
            fixture=fixture,
        )
        for ordinal, request in enumerate(schedule, start=1):
            call_cursor = len(adapter.export_call_records())
            requests.append(
                _execute_request(
                    ordinal=ordinal,
                    request=request,
                    case=fixture,
                    adapter=adapter,
                    call_cursor=call_cursor,
                    governance_manifest=governance_manifest,
                )
            )
        capture_manifest = _capture_outcome_manifest(adapter)
        namespace_cleanup = _wait_for_namespace_cleanup(
            adapter,
            adapter.cleanup(),
            timeout_ms=120_000,
        )
        adapter_cleaned = True
        worker_before_close = dict(session.worker_status())
        projection = dict(session.projection_metrics())
        call_records = [asdict(record) for record in adapter.export_call_records()]
    except BaseException as exc:  # noqa: BLE001 - always seal and clean up
        primary_error = _error_receipt(exc)
    finally:
        if adapter is not None and not adapter_cleaned:
            try:
                namespace_cleanup = _wait_for_namespace_cleanup(
                    adapter,
                    adapter.cleanup(),
                    timeout_ms=120_000,
                )
                adapter_cleaned = True
            except Exception as exc:  # noqa: BLE001 - sealed cleanup evidence
                cleanup_errors.append(
                    {"component": "fixture_namespace", **_error_receipt(exc)}
                )
        if adapter is not None:
            call_records = [asdict(record) for record in adapter.export_call_records()]
        _close_transport(transport, cleanup_errors)
        if mcp_log is not None:
            try:
                mcp_log.close()
            except Exception as exc:  # noqa: BLE001 - sealed cleanup evidence
                cleanup_errors.append({"component": "mcp_log", **_error_receipt(exc)})
        try:
            runtime_cleanup = dict(session.close())
        except Exception as exc:  # noqa: BLE001 - sealed cleanup evidence
            runtime_cleanup = {"status": "FAIL", **_error_receipt(exc)}
            cleanup_errors.append(
                {"component": "runtime_session", **_error_receipt(exc)}
            )
        ownership_path = runtime_root / "runtime-ownership.json"
        if ownership_path.is_file():
            try:
                ownership_after = json.loads(ownership_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                cleanup_errors.append(
                    {"component": "runtime_ownership", **_error_receipt(exc)}
                )

    final_identity_check = _run_lock_identity_check(run_lock)
    (
        projection_terminal,
        processing_leases,
        expired_leases,
        terminal_lease_residue,
        projection_watermark,
    ) = _projection_terminal(projection)
    api_identity = ownership_after.get("api_process") or ownership_before.get(
        "api_process"
    )
    worker_identity = ownership_after.get("worker_process") or ownership_before.get(
        "worker_process"
    )
    persistent_worker = runtime_cleanup.get("persistent_worker")
    request_status_counts = Counter(str(row.get("runtime_status")) for row in requests)
    conditions = {
        "no_primary_error": primary_error is None,
        "authority_and_run_lock_identity_pass": final_identity_check.get("status")
        == "PASS",
        "owned_orphan_preflight_pass": orphan_preflight.get("status") == "PASS",
        "one_fresh_runtime_composition": (
            runtime.get("persistent_worker") is True
            and runtime.get("worker_starts") == 1
            and runtime.get("data_mode") == "SYNTHETIC_ONLY"
        ),
        "dense_retrieval_enabled": runtime.get("retrieval_evidence_dense_enabled")
        is True,
        "projection_barrier_ready": readiness.get("status") == "READY",
        "fixture_event_denominator_exact": (
            len(fixture.history_events) == FIXTURE_EVENT_COUNT
            and capture_manifest.get("capture_record_count") == FIXTURE_EVENT_COUNT
            and capture_manifest.get("succeeded_record_count") == FIXTURE_EVENT_COUNT
            and capture_manifest.get("failed_record_count") == 0
        ),
        "ten_distinct_query_classes_once": (
            len(requests) == QUERY_CLASS_COUNT
            and len({row.get("query_class") for row in requests}) == QUERY_CLASS_COUNT
            and all(row.get("attempt_count") == 1 for row in requests)
        ),
        "ten_context_terminals_pass": all(
            row.get("status") == "PASS"
            and row.get("terminal_type") == "CONTEXT_TERMINAL"
            and row.get("runtime_typed_terminal") is True
            and row.get("context_contract_valid") is True
            and row.get("fixture_expectation_satisfied") is True
            for row in requests
        )
        and len(requests) == QUERY_CLASS_COUNT,
        "ten_archives_live_validated": all(
            row.get("evidence_archive_validated") is True
            and isinstance(row.get("evidence_archive"), Mapping)
            for row in requests
        )
        and len(requests) == QUERY_CLASS_COUNT,
        "ten_exactly_once_resolves_no_retry": all(
            row.get("exactly_once") is True
            and row.get("resolve_call_count") == 1
            and row.get("logical_mcp_call_delta") == 1
            and row.get("automatic_retry_count") == 0
            and row.get("retry_policy_max_retries") == 0
            for row in requests
        )
        and len(requests) == QUERY_CLASS_COUNT,
        "system_failure_as_semantic_abstention_zero": all(
            row.get("system_failure_as_semantic_abstention") is False
            for row in requests
        ),
        "evaluation_failure_count_zero": all(
            row.get("evaluation_failure_class") is None for row in requests
        ),
        "reader_answer_judge_calls_zero": True,
        "benchmark_case_count_zero": True,
        "canonical_claim_count_zero": (
            isinstance(adapter, DG15MilaiMcpAdapter)
            and adapter.stats().claim_count == 0
        ),
        "namespace_cleanup_terminal_20_of_20": (
            namespace_cleanup.get("cleanup_terminal") is True
            and namespace_cleanup.get("evidence_count") == FIXTURE_EVENT_COUNT
            and namespace_cleanup.get("accepted_count") == FIXTURE_EVENT_COUNT
            and namespace_cleanup.get("failed_count") == 0
            and namespace_cleanup.get("projection_purged_count")
            == FIXTURE_EVENT_COUNT
            and namespace_cleanup.get("primary_bytes_terminal_count")
            == FIXTURE_EVENT_COUNT
            and namespace_cleanup.get("primary_bytes_erased_count")
            == FIXTURE_EVENT_COUNT
        ),
        "projection_delivery_matrix_exact_12": projection_terminal,
        "projection_terminal_watermark_60": projection_watermark
        == EXPECTED_PROJECTION_TERMINAL_WATERMARK,
        "projection_leases_zero": (
            processing_leases == 0
            and expired_leases == 0
            and terminal_lease_residue == 0
        ),
        "worker_running_before_close": worker_before_close.get("status") == "RUNNING",
        "runtime_cleanup_pass": runtime_cleanup.get("status") == "PASS",
        "persistent_worker_stopped": (
            isinstance(persistent_worker, Mapping)
            and persistent_worker.get("status") == "STOPPED"
            and persistent_worker.get("return_code") == 0
        ),
        "runtime_ownership_released": (
            ownership_after.get("schema_version")
            == "milai-local-runtime-ownership-v0.1"
            and ownership_after.get("run_id") == run_id
            and ownership_after.get("status") == "RELEASED"
        ),
        "api_process_absent": _exact_process_absent(api_identity),
        "worker_process_absent": _exact_process_absent(worker_identity),
        "api_port_closed": _port_closed(runtime.get("api_base_url")),
        "cleanup_errors_zero": not cleanup_errors,
        "formal_warm_successor_still_not_authorized": True,
        "formal_holdout_not_consumed": True,
    }
    passed = all(conditions.values())
    results: dict[str, object] = {
        "schema_version": "mila-mvp01-u0-warm-repair-probe-v0.2",
        "run_id": run_id,
        "status": "PASS" if passed else "FAIL",
        "classification": "SYNTHETIC_ONLY_10_CLASS_REPAIR_DIAGNOSTIC",
        "scope_identity": SCOPE_IDENTITY,
        "run_lock_sha256": run_lock_sha256,
        "request_count": len(requests),
        "query_class_count": len({row.get("query_class") for row in requests}),
        "logical_attempt_count": sum(
            int(row.get("attempt_count", 0))
            for row in requests
            if isinstance(row.get("attempt_count"), int)
            and not isinstance(row.get("attempt_count"), bool)
        ),
        "context_terminal_count": sum(row.get("status") == "PASS" for row in requests),
        "semantic_abstention_count": sum(
            row.get("semantic_abstention") is True for row in requests
        ),
        "runtime_status_counts": dict(sorted(request_status_counts.items())),
        "evidence_archive_count": sum(
            isinstance(row.get("evidence_archive"), Mapping) for row in requests
        ),
        "benchmark_case_count": 0,
        "reader_calls": 0,
        "answer_calls": 0,
        "judge_calls": 0,
        "formal_holdout_consumed": False,
        "formal_warm_successor_authorized": False,
        "next_authority_required": "INDEPENDENT_AUDITOR_GO",
        "conditions": conditions,
        "primary_error": primary_error,
        "cleanup_errors": cleanup_errors,
        "requests": _json_value(requests),
        "runtime": _json_value(runtime),
        "readiness": _json_value(readiness),
        "capture_outcome_manifest": _json_value(capture_manifest),
        "worker_before_close": _json_value(worker_before_close),
        "projection_metrics": _json_value(projection),
        "projection_terminal_watermark": projection_watermark,
        "namespace_cleanup": _json_value(namespace_cleanup),
        "runtime_cleanup": _json_value(runtime_cleanup),
        "runtime_ownership": _json_value(ownership_after),
        "call_records": _json_value(call_records),
        "final_identity_check": _json_value(final_identity_check),
        "process_cleanup": {
            "api_exact_process_absent": conditions["api_process_absent"],
            "worker_exact_process_absent": conditions["worker_process_absent"],
            "api_port_closed": conditions["api_port_closed"],
        },
        "artifacts": {
            "run_lock": {"path": "run-lock.json", "sha256": run_lock_sha256},
            "runtime_log": {
                "path": "runtime/attempt-001/runtime.log",
                "sha256": (
                    _sha256_file(runtime_root / "runtime.log")
                    if (runtime_root / "runtime.log").is_file()
                    else None
                ),
            },
            "mcp_log": {
                "path": "runtime/attempt-001/mcp.log",
                "sha256": (
                    _sha256_file(mcp_log_path) if mcp_log_path.is_file() else None
                ),
            },
            "runtime_ownership": {
                "path": "runtime/attempt-001/runtime-ownership.json",
                "sha256": (
                    _sha256_file(runtime_root / "runtime-ownership.json")
                    if (runtime_root / "runtime-ownership.json").is_file()
                    else None
                ),
            },
        },
        "environment": {"pid": os.getpid(), "python": sys.version},
    }
    results_path = output_root / "results.json"
    _atomic_json(results_path, results)
    terminal: dict[str, object] = {
        "schema_version": "mila-mvp01-u0-warm-repair-probe-terminal-v0.2",
        "run_id": run_id,
        "status": PASS_STATUS if passed else FAIL_STATUS,
        "block_complete": False,
        "goal_complete": False,
        "formal_warm_successor_authorized": False,
        "next_authority_required": "INDEPENDENT_AUDITOR_GO",
        "request_count": len(requests),
        "query_class_count": len({row.get("query_class") for row in requests}),
        "context_terminal_count": sum(row.get("status") == "PASS" for row in requests),
        "evidence_archive_count": sum(
            isinstance(row.get("evidence_archive"), Mapping) for row in requests
        ),
        "reader_answer_judge_calls": 0,
        "benchmark_case_count": 0,
        "formal_holdout_consumed": False,
        "run_lock_sha256": run_lock_sha256,
        "results_sha256": _sha256_file(results_path),
    }
    _atomic_json(output_root / "terminal.json", terminal)
    return terminal


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser


def main() -> int:
    args = _parser().parse_args()
    terminal = run_probe(run_id=args.run_id, output_root=args.output_root.resolve())
    print(json.dumps(terminal, ensure_ascii=False, sort_keys=True))
    return 0 if terminal["status"] == PASS_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
