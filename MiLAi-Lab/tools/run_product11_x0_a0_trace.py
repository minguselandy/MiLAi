#!/usr/bin/env python3
"""Capture the Product-11 opened-dev fixture and freeze a label-blind A0 trace."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_product09_codex_lifecycle as p09
import run_product10_context as p10
from milai_lab.product11 import canonical_sha256, validate_source_fixture
from milai_lab.product_adapter.manifest import load_product_lock, verify_product_lock

LAB = Path(__file__).resolve().parents[1]
PRODUCT = LAB.parent / "MiLAi-Product"
RUNTIME = PRODUCT / "runtime"
DEFAULT_FIXTURE = LAB / "data/fixtures/product11-opened-dev24.v0.6.json"
DEFAULT_MANIFEST = LAB / "data/manifests/product11-opened-dev24.v0.7.json"
DEFAULT_PRODUCT_LOCK = LAB / "data/locks/product10-final-product.lock.json"
QUESTION_DATE = "2026-02-01T00:00:00Z"
_RUN_ID = p10._RUN_ID


class Product11X0TraceError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    path.chmod(0o600)


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)
    path.chmod(0o600)


def _load_source(fixture_path: Path, manifest_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(fixture, dict) or not isinstance(manifest, dict):
        raise Product11X0TraceError("Product-11 source or manifest is not an object")
    source_summary = validate_source_fixture(fixture)
    expected_name = fixture_path.name
    files = manifest.get("files")
    if (
        manifest.get("schema_version")
        not in {
            "milai-product11-dataset-manifest-v0.2",
            "milai-product11-dataset-manifest-v0.3",
            "milai-product11-dataset-manifest-v0.4",
            "milai-product11-dataset-manifest-v0.5",
            "milai-product11-dataset-manifest-v0.6",
            "milai-product11-dataset-manifest-v0.7",
        }
        or manifest.get("classification") != "OPENED_DEVELOPMENT_ONLY"
        or manifest.get("formal_source") is not False
        or manifest.get("case_count") != source_summary["case_count"]
        or manifest.get("case_order_sha256") != source_summary["case_order_sha256"]
        or not isinstance(files, Mapping)
        or files.get(expected_name) != _sha256_file(fixture_path)
        or manifest.get("source_fixture_semantic_sha256") != canonical_sha256(fixture)
    ):
        raise Product11X0TraceError("Product-11 source manifest identity validation failed")
    return fixture, source_summary


def _event_type(speaker: str) -> str:
    try:
        return {
            "user": "USER_MESSAGE",
            "assistant": "ASSISTANT_MESSAGE",
            "tool": "TOOL_RESULT",
            "system": "SESSION_MARKER",
        }[speaker]
    except KeyError as exc:
        raise Product11X0TraceError(f"unsupported fixture speaker: {speaker}") from exc


def _events(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    case_id = str(case["case_id"])
    project = p10._case_project(case_id)
    result: list[dict[str, Any]] = []
    sessions = case.get("sessions")
    if not isinstance(sessions, list):
        raise Product11X0TraceError(f"case {case_id} sessions are invalid")
    for session in sessions:
        if not isinstance(session, Mapping):
            raise Product11X0TraceError(f"case {case_id} session is invalid")
        session_id = str(session["session_id"])
        turns = session.get("turns")
        if not isinstance(turns, list):
            raise Product11X0TraceError(f"case {case_id} turns are invalid")
        turn_ids = [str(turn["turn_id"]) for turn in turns if isinstance(turn, Mapping)]
        if len(turn_ids) != len(turns):
            raise Product11X0TraceError(f"case {case_id} has an invalid turn")
        for ordinal, turn in enumerate(turns):
            assert isinstance(turn, Mapping)
            identity = f"{case_id}\0{session_id}\0{turn['turn_id']}"
            observed_at = str(turn["observed_at"])
            parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            if parsed.utcoffset() is None:
                raise Product11X0TraceError(f"case {case_id} has a naive timestamp")
            result.append(
                {
                    "schema_version": "host-agent-event-v1",
                    "event_id": "p11-" + hashlib.sha256(identity.encode()).hexdigest()[:40],
                    "event_type": _event_type(str(turn["speaker"])),
                    "session_id": session_id,
                    "source_id": str(turn["turn_ref"]),
                    "subject_id": f"product11:{case_id}",
                    "observed_at": parsed.isoformat(),
                    "content": str(turn["text"]),
                    "turn_id": str(turn["turn_id"]),
                    "turn_ordinal": ordinal,
                    "round_id": f"{session_id}:round:{ordinal // 2}",
                    "round_ordinal": ordinal // 2,
                    **({"previous_turn_id": turn_ids[ordinal - 1]} if ordinal else {}),
                    **(
                        {"next_turn_id": turn_ids[ordinal + 1]}
                        if ordinal + 1 < len(turn_ids)
                        else {}
                    ),
                    "_project": project,
                }
            )
    return result


def _capture_events(
    environment: dict[str, str], events: Sequence[Mapping[str, Any]], *, workers: int
) -> list[str]:
    def capture(raw: Mapping[str, Any]) -> str:
        event = dict(raw)
        project = str(event.pop("_project"))
        result = p09._capture(
            environment,
            project=project,
            event=event,
            data_classification="SYNTHETIC",
        )
        receipt = result.get("receipt")
        if not isinstance(receipt, Mapping) or not isinstance(receipt.get("outbox_id"), str):
            raise Product11X0TraceError("Product-11 capture receipt is malformed")
        return str(receipt["outbox_id"])

    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(capture, events))


def _capture_one_case(
    *,
    run_id: str,
    case: Mapping[str, Any],
    base_environment: Mapping[str, str],
    work_root: Path,
    capture_workers: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    case_id = str(case["case_id"])
    case_root = work_root / "capture" / case_id
    case_root.mkdir(parents=True, exist_ok=True)
    environment = p10._case_environment(
        base_environment,
        run_id=run_id,
        case_id=case_id,
        api_port=p09._free_port(),
        blob_root=case_root / "blobs",
    )
    processes = p09.ProcessGroup(case_root)
    try:
        p09._start_runtime(processes, environment)
        events = _events(case)
        outbox_ids = _capture_events(environment, events, workers=capture_workers)
        readiness = p10._wait_projection_batches(environment, outbox_ids)
        return {
            "status": "CAPTURED",
            "case_id": case_id,
            "event_count": len(events),
            "outbox_count": len(outbox_ids),
            "projection_status": readiness.get("status"),
            "tenant_scope_digest": canonical_sha256(environment["MILAI_TENANT_ID"]),
            "project_scope_digest": canonical_sha256(p10._case_project(case_id)),
            "environment": environment,
            "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
        }
    except Exception as exc:
        return {
            "status": "CAPTURE_FAILED",
            "case_id": case_id,
            "failure": {"type": type(exc).__name__, "message": p10._redact(exc)},
            "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
        }
    finally:
        processes.stop()


def _record(case: Mapping[str, Any]) -> dict[str, str]:
    return {"question": str(case["question"]), "question_date": QUESTION_DATE}


def _trace_one_case(
    *,
    run_id: str,
    case: Mapping[str, Any],
    environment: Mapping[str, str],
    source_snapshot_as_of: str,
    work_root: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    case_id = str(case["case_id"])
    case_root = work_root / "trace" / "a0" / case_id
    case_root.mkdir(parents=True, exist_ok=True)
    current_environment = p10._case_environment(
        environment,
        run_id=run_id,
        case_id=case_id,
        api_port=p09._free_port(),
        blob_root=Path(environment["MILAI_BLOB_ROOT"]),
    )
    current_environment.update(
        {
            "MILAI_READER_INFORMATIONAL_SOFT_ADMISSION_V0_2_ENABLED": "false",
            "MILAI_READER_INSTANCE_PRESERVING_ADMISSION_V0_1_ENABLED": "false",
        }
    )
    processes = p09.ProcessGroup(case_root)
    try:
        record = _record(case)
        report, testkit_latency = p10._run_testkit(
            run_id=run_id,
            case_id=case_id,
            record=record,
            environment=current_environment,
            source_snapshot_as_of=source_snapshot_as_of,
            arm="A0",
        )
        api = processes.start(
            "api",
            [str(p09.API_EXE)],
            cwd=RUNTIME,
            env=p09._clean_environment(current_environment),
        )
        p09._wait_http(f"{current_environment['MILAI_BASE_URL']}/health/ready", api)
        mcp_environment = dict(current_environment)
        mcp_environment["MILAI_AGENT_AS_OF"] = p10._operational_reference_time(
            source_snapshot_as_of
        )
        mcp_port = p09._free_port()
        inbound_token = secrets.token_urlsafe(40)
        p09._start_mcp(
            processes,
            mcp_environment,
            port=mcp_port,
            inbound_token=inbound_token,
            project=p10._case_project(case_id),
            name="mcp",
        )
        mcp_started = time.perf_counter()
        raw_mcp = asyncio.run(
            p10._mcp_call(
                f"http://127.0.0.1:{mcp_port}/mcp",
                inbound_token,
                p10._query(record),
            )
        )
        mcp_latency = round((time.perf_counter() - mcp_started) * 1_000, 3)
        if raw_mcp.get("schema_version") != "memory-evidence-context-v1":
            raise Product11X0TraceError("MCP renderer schema drifted")
        if raw_mcp.get("profile", {}).get("resolved") != p10.PROFILE:
            raise Product11X0TraceError("MCP budget profile drifted")
        if not p10._join_matches(report, raw_mcp):
            raise Product11X0TraceError("Product testkit and MCP identity join diverged")
        sanitized = p10._sanitize_mcp(raw_mcp)
        identities = p10._trace_identities(report)
        rendered_evidence, rendered_turns = p10._mcp_identities(sanitized)
        expected_prefix = f"p11://{case_id}/"
        trace = report.get("product_trace")
        if not isinstance(trace, Mapping):
            raise Product11X0TraceError("Product trace is absent")
        raw_candidates = trace.get("candidates")
        candidates = raw_candidates if isinstance(raw_candidates, list) else []
        hydrated = sum(
            bool(item.get("hydrated_span_identities"))
            for item in candidates
            if isinstance(item, Mapping)
        )
        return {
            "schema_version": "milai-product11-x0-a0-case-trace-v0.1",
            "status": "TRACE_COMPLETE",
            "case_id": case_id,
            "arm": "A0",
            "arm_kind": "PRODUCT_TESTKIT_PLUS_PRODUCT_BLACK_BOX",
            "source_snapshot_as_of": source_snapshot_as_of,
            "query_sha256": canonical_sha256(p10._query(record)),
            "tenant_scope_digest": canonical_sha256(current_environment["MILAI_TENANT_ID"]),
            "project_scope_digest": canonical_sha256(p10._case_project(case_id)),
            "product_testkit": report,
            "mcp": sanitized,
            "identity_sets": {
                **identities,
                "rendered_evidence_ids": rendered_evidence,
                "rendered_turn_refs": rendered_turns,
            },
            "counts": {
                "scanned_occurrences": len(trace.get("occurrences", [])),
                "unique_evidence": len(identities["post_identity_evidence_ids"]),
                "hydrated_units": hydrated,
                "admitted_units": len(identities["admitted_evidence_ids"]),
                "rendered_units": len(rendered_evidence),
                "visible_token_estimate": sanitized["visible_token_estimate"],
                "official_memory_calls": 1,
            },
            "latency_ms": {
                "testkit_normal_baseline_traced": testkit_latency,
                "http_mcp": mcp_latency,
                "case_total": round((time.perf_counter() - started) * 1_000, 3),
            },
            "invariants": {
                "mcp_identity_join_exact": True,
                "cross_namespace_source_count": sum(
                    not value.startswith(expected_prefix) for value in rendered_turns
                ),
                "labels_loaded": False,
                "label_fields_present": False,
                "raw_evidence_text_emitted": False,
                "canonical_mutation": False,
                "reader_calls": 0,
                "vllm_calls": 0,
                "automatic_semantic_retries": 0,
                "instance_preserving_treatment_enabled": False,
            },
        }
    except Exception as exc:
        return {
            "schema_version": "milai-product11-x0-a0-case-trace-v0.1",
            "status": "TRACE_FAILED",
            "case_id": case_id,
            "arm": "A0",
            "failure": {"type": type(exc).__name__, "message": p10._redact(exc)},
            "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
        }
    finally:
        processes.stop()


def _command_material(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "runner": "tools/run_product11_x0_a0_trace.py",
        "run_id": args.run_id,
        "arm": "A0_SOURCE_ONLY",
        "output": str(args.output.resolve()),
        "source_fixture": str(args.source_fixture.resolve()),
        "dataset_manifest": str(args.dataset_manifest.resolve()),
        "product_lock": str(args.product_lock.resolve()),
        "capture_workers": args.capture_workers,
        "case_concurrency": 1,
        "profile": p10.PROFILE,
        "budget": p10.BUDGET,
        "labels": "ABSENT_AND_NOT_LOADED",
        "formal": "ABSENT_AND_NOT_ACCESSED",
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    started_at = datetime.now(UTC).isoformat()
    args.output.mkdir(parents=True, exist_ok=False)
    fixture, source_summary = _load_source(args.source_fixture, args.dataset_manifest)
    lock = load_product_lock(args.product_lock)
    lock_verification = verify_product_lock(lock, PRODUCT)
    if not lock_verification.valid:
        raise Product11X0TraceError(
            "Product behavior lock verification failed: "
            + "; ".join(lock_verification.errors)
        )
    for executable in (
        p09.OPS_EXE,
        p09.ALEMBIC_EXE,
        p09.API_EXE,
        p09.WORKER_EXE,
        p09.MCP_EXE,
        p09.HOOK_EXE,
        p10.TRACE_TESTKIT_EXE,
    ):
        if not executable.is_file():
            raise Product11X0TraceError(f"required executable is missing: {executable}")
    command = _command_material(args)
    preseal = {
        "schema_version": "milai-product11-x0-a0-preseal-v0.1",
        "run_identity": args.run_id,
        "arm": "A0_SOURCE_ONLY",
        "sealed_at": started_at,
        "product_tree_sha256": lock.tree_sha256,
        "product_lock_digest": lock.digest,
        "lab_runner_sha256": _sha256_file(Path(__file__).resolve()),
        "imported_product10_runner_sha256": _sha256_file(Path(p10.__file__).resolve()),
        "command": command,
        "command_sha256": canonical_sha256(command),
        "source_fixture_file_sha256": _sha256_file(args.source_fixture),
        "source_fixture_semantic_sha256": canonical_sha256(fixture),
        "source_manifest_sha256": _sha256_file(args.dataset_manifest),
        "case_order_sha256": source_summary["case_order_sha256"],
        "labels_present_in_command": False,
        "labels_loaded_for_product_trace": False,
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
        "scored_case_count": 0,
        "profile": p10.PROFILE,
        "budget": p10.BUDGET,
    }
    _write_json(args.output / "preseal.json", preseal)

    postgres_port = p09._free_port()
    bootstrap_port = p09._free_port()
    compose_project = f"{args.run_id}-pg"
    capture_rows: list[dict[str, Any]] = []
    trace_rows: list[dict[str, Any]] = []
    failure: dict[str, Any] | None = None
    database_before: dict[str, int] | None = None
    database_after: dict[str, int] | None = None
    source_snapshot = ""
    with tempfile.TemporaryDirectory(prefix="milai-p11-x0-a0-") as temporary:
        work_root = Path(temporary)
        env_file = work_root / "runtime.env"
        p09._command(
            [
                str(p09.OPS_EXE),
                "init",
                "--env-file",
                str(env_file),
                "--blob-root",
                str(work_root / "bootstrap-blobs"),
                "--postgres-port",
                str(postgres_port),
                "--api-port",
                str(bootstrap_port),
            ],
            cwd=RUNTIME,
        )
        base_environment = p09._load_environment(env_file)
        compose = [
            "docker",
            "compose",
            "--project-name",
            compose_project,
            "--env-file",
            str(env_file),
            "--file",
            str(RUNTIME / "compose.yaml"),
        ]
        try:
            p09._command([*compose, "up", "--detach", "postgres"], cwd=RUNTIME, timeout=120)
            deadline = time.monotonic() + 90
            while True:
                migration = p09._command(
                    [str(p09.ALEMBIC_EXE), "-c", "alembic.ini", "upgrade", "head"],
                    cwd=RUNTIME,
                    env=p09._clean_environment(
                        {
                            "MILAI_MIGRATION_DATABASE_URL": base_environment[
                                "MILAI_MIGRATION_DATABASE_URL"
                            ]
                        }
                    ),
                    timeout=120,
                    check=False,
                )
                if migration.returncode == 0:
                    break
                if time.monotonic() >= deadline:
                    raise Product11X0TraceError("fresh PostgreSQL migration did not become ready")
                time.sleep(1)
            database_before = p09._database_counts(compose)
            if database_before != {"evidence": 0, "projection": 0, "canonical": 0}:
                raise Product11X0TraceError("fresh PostgreSQL did not start empty")
            raw_cases = fixture["cases"]
            assert isinstance(raw_cases, list)
            for case in raw_cases:
                assert isinstance(case, Mapping)
                capture_rows.append(
                    _capture_one_case(
                        run_id=args.run_id,
                        case=case,
                        base_environment=base_environment,
                        work_root=work_root,
                        capture_workers=args.capture_workers,
                    )
                )
            _write_jsonl(
                args.output / "capture-trace.jsonl",
                [
                    {key: value for key, value in row.items() if key != "environment"}
                    for row in capture_rows
                ],
            )
            failed_capture = [row for row in capture_rows if row["status"] != "CAPTURED"]
            if failed_capture:
                raise Product11X0TraceError(f"{len(failed_capture)} cases failed capture")
            source_snapshot = datetime.now(UTC).isoformat()
            captures_by_case = {str(row["case_id"]): row for row in capture_rows}
            for case in raw_cases:
                assert isinstance(case, Mapping)
                case_id = str(case["case_id"])
                trace_rows.append(
                    _trace_one_case(
                        run_id=args.run_id,
                        case=case,
                        environment=captures_by_case[case_id]["environment"],
                        source_snapshot_as_of=source_snapshot,
                        work_root=work_root,
                    )
                )
            _write_jsonl(args.output / "product-trace.redacted.jsonl", trace_rows)
            failed_trace = [row for row in trace_rows if row["status"] != "TRACE_COMPLETE"]
            if failed_trace:
                raise Product11X0TraceError(
                    f"{len(failed_trace)} cases failed Product/MCP tracing"
                )
            database_after = p09._database_counts(compose)
            if database_after["canonical"] != database_before["canonical"]:
                raise Product11X0TraceError("A0 trace mutated Canonical tables")
            if any(
                row["invariants"]["cross_namespace_source_count"] != 0 for row in trace_rows
            ):
                raise Product11X0TraceError("A0 returned a cross-case source identity")
        except Exception as exc:
            failure = {"type": type(exc).__name__, "message": p10._redact(exc)}
        finally:
            cleanup = p10._cleanup_receipt(compose, compose_project)

    _write_json(args.output / "cleanup-receipt.json", cleanup)
    valid = (
        failure is None
        and len(capture_rows) == 24
        and len(trace_rows) == 24
        and all(row.get("status") == "TRACE_COMPLETE" for row in trace_rows)
        and database_before == {"evidence": 0, "projection": 0, "canonical": 0}
        and database_after is not None
        and database_after["canonical"] == 0
        and cleanup["run_owned_database_volume_removed"] is True
    )
    latencies = [
        float(row["latency_ms"]["http_mcp"])
        for row in trace_rows
        if row.get("status") == "TRACE_COMPLETE" and isinstance(row.get("latency_ms"), Mapping)
    ]
    summary = {
        "schema_version": "milai-product11-x0-a0-summary-v0.1",
        "status": (
            "PASS_PRODUCT11_X0_A0_TRACE_CAPTURED"
            if valid
            else "FAIL_PRODUCT11_X0_A0_TRACE_INVALID"
        ),
        "run_identity": args.run_id,
        "source_snapshot_as_of": source_snapshot or None,
        "capture_case_count": len(capture_rows),
        "capture_event_count": sum(int(row.get("event_count", 0)) for row in capture_rows),
        "trace_case_count": len(trace_rows),
        "scored_case_count": 0,
        "database_counts_before": database_before,
        "database_counts_after": database_after,
        "latency_ms": {
            "http_mcp_p50": p10._percentile(latencies, 0.50),
            "http_mcp_p95": p10._percentile(latencies, 0.95),
        },
        "invariants": {
            "source_only": True,
            "trace_written_before_human_labels": bool(trace_rows),
            "labels_loaded": False,
            "product_label_access": 0,
            "formal_files_accessed": False,
            "formal_cases_scored": 0,
            "canonical_mutation": (
                database_after["canonical"] - database_before["canonical"]
                if database_before is not None and database_after is not None
                else None
            ),
            "reader_calls": 0,
            "vllm_calls": 0,
            "automatic_semantic_retries": 0,
            "votes": 0,
            "case_concurrency": 1,
            "run_owned_database_volume_removed": cleanup[
                "run_owned_database_volume_removed"
            ],
        },
        "x0_human_seal_status": "PENDING_NOT_EVALUATED",
        "effect_claim_status": "NOT_TESTED",
        "failure": failure,
        "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
    }
    _write_json(args.output / "summary.json", summary)
    trace_path = args.output / "product-trace.redacted.jsonl"
    capture_path = args.output / "capture-trace.jsonl"
    cleanup_path = args.output / "cleanup-receipt.json"
    run_bundle = {
        **preseal,
        "schema_version": "milai-product11-x0-a0-run-bundle-v0.1",
        "source_snapshot_as_of": source_snapshot or None,
        "redacted_trace_sha256": _sha256_file(trace_path) if trace_path.is_file() else None,
        "capture_trace_sha256": _sha256_file(capture_path) if capture_path.is_file() else None,
        "cleanup_receipt_sha256": _sha256_file(cleanup_path),
        "summary_sha256": _sha256_file(args.output / "summary.json"),
        "labels_loaded": False,
        "formal_files_accessed": False,
        "formal_cases_scored": 0,
        "scored_case_count": 0,
        "run_valid": valid,
    }
    _write_json(args.output / "run-bundle.json", run_bundle)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--dataset-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--product-lock", type=Path, default=DEFAULT_PRODUCT_LOCK)
    parser.add_argument("--capture-workers", type=int, default=8)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not _RUN_ID.fullmatch(args.run_id):
        raise SystemExit("run-id must contain 8-48 lowercase alphanumeric/hyphen characters")
    if args.output.exists():
        raise SystemExit("output already exists")
    if not 1 <= args.capture_workers <= 8:
        raise SystemExit("capture-workers must be 1..8")
    try:
        summary = run(args)
    except Exception as exc:
        print(
            "Product-11 X0 A0 trace failed before run artifact initialization: "
            f"{type(exc).__name__}: {p10._redact(exc)}",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["status"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
