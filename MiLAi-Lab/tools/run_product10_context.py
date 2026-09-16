#!/usr/bin/env python3
"""Run the sealed Product-10 A0 Context-only trace and first-loss audit."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

import run_product09_codex_lifecycle as p09
import run_product09_codex_lme as p09_lme
from milai_lab.product10 import (
    InstanceGroup,
    canonical_sha256,
    distinct_instance_coverage,
    duplicate_instance_rate,
    first_loss,
    validate_label_bundle,
)
from milai_lab.product_adapter.manifest import load_product_lock, verify_product_lock

LAB = Path(__file__).resolve().parents[1]
PRODUCT = LAB.parent / "MiLAi-Product"
RUNTIME = PRODUCT / "runtime"
TRACE_TESTKIT_EXE = RUNTIME / ".venv/bin/milai-retrieval-trace-testkit"
DEFAULT_DATASET_MANIFEST = LAB / "data/manifests/longmemeval-s-cleaned-500.json"
DEFAULT_MEMBERSHIP = LAB / "data/manifests/product10-opened-dev24.json"
DEFAULT_LABELS = LAB / "data/labels/product10-instance-groups.jsonl"
DEFAULT_PRODUCT_LOCK = LAB / "data/locks/product10-a0-product.lock.json"
PROFILE = "MCP_INTERACTIVE_WIDE_V01"
BUDGET = {
    "max_results": 50,
    "max_candidates": 120,
    "max_context_tokens": 16_384,
    "max_latency_ms": 5_000,
}
CODEX_IDENTITY = {
    "provider": "OpenAI Codex CLI",
    "model": "gpt-5.6-sol",
    "reasoning_effort": "xhigh",
    "service_tier": "default",
    "ignore_user_config": True,
}
_RUN_ID = re.compile(r"^[a-z0-9-]{8,48}$")
_SECRET_PATTERN = re.compile(
    r"(?i)(token|secret|password|authorization|bearer)[=: ]+[^\s,;]+"
)


class Product10RunError(RuntimeError):
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


def _redact(value: object) -> str:
    return _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=<redacted>", str(value))[
        -4_000:
    ]


def _load_membership(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Product10RunError("membership is not an object")
    cases = value.get("cases")
    case_ids = value.get("case_ids")
    if (
        value.get("schema_version")
        != "milai-product10-opened-dev24-membership-v0.1"
        or value.get("case_count") != 24
        or not isinstance(cases, list)
        or not isinstance(case_ids, list)
        or [row.get("case_id") for row in cases if isinstance(row, Mapping)] != case_ids
        or canonical_sha256(case_ids) != value.get("case_order_sha256")
        or value.get("instance_identity_fields_present") is not False
        or value.get("answer_material_present") is not False
    ):
        raise Product10RunError("membership seal validation failed")
    forbidden = {
        "instance_groups",
        "acceptable_evidence_ids",
        "acceptable_turn_refs",
        "answer",
        "reference_answer",
    }
    if forbidden.intersection(_recursive_keys(value)):
        raise Product10RunError("membership seal contains scorer-only fields")
    return value


def _recursive_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return {str(key) for key in value}.union(
            *( _recursive_keys(item) for item in value.values())
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return set().union(*(_recursive_keys(item) for item in value)) if value else set()
    return set()


def _load_population(
    manifest_path: Path,
    membership: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping):
        raise Product10RunError("dataset manifest is not an object")
    filename = manifest.get("split_files", {}).get("population_500")
    root = manifest.get("external_root")
    expected = manifest.get("file_sha256", {}).get(filename)
    if not isinstance(root, str) or not isinstance(filename, str) or not isinstance(expected, str):
        raise Product10RunError("dataset manifest is malformed")
    dataset_path = Path(root) / filename
    if _sha256_file(dataset_path) != expected or expected != membership.get("dataset_sha256"):
        raise Product10RunError("dataset identity does not match membership seal")
    if _sha256_file(manifest_path) != membership.get("dataset_manifest_sha256"):
        raise Product10RunError("dataset manifest identity does not match membership seal")
    population = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(population, list) or len(population) != 500:
        raise Product10RunError("dataset population identity is invalid")
    by_id = {
        str(row["question_id"]): dict(row)
        for row in population
        if isinstance(row, Mapping) and isinstance(row.get("question_id"), str)
    }
    case_ids = [str(value) for value in membership["case_ids"]]
    if any(case_id not in by_id for case_id in case_ids):
        raise Product10RunError("membership case is absent from pinned dataset")
    for item in membership["cases"]:
        case_id = str(item["case_id"])
        record = by_id[case_id]
        if canonical_sha256(record.get("question")) != item.get("question_sha256"):
            raise Product10RunError(f"case {case_id} question identity drifted")
        if canonical_sha256(record.get("answer")) != item.get("reference_answer_sha256"):
            raise Product10RunError(f"case {case_id} reference identity drifted")
    return {case_id: by_id[case_id] for case_id in case_ids}


def _load_labels(path: Path, expected_sha256: str) -> dict[str, dict[str, Any]]:
    if _sha256_file(path) != expected_sha256:
        raise Product10RunError("instance label identity drifted after trace capture")
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if any(not isinstance(row, Mapping) for row in rows):
        raise Product10RunError("instance label seal contains a non-object row")
    validate_label_bundle(rows)
    return {str(row["case_id"]): dict(row) for row in rows[1:]}


def _case_environment(
    base: Mapping[str, str],
    *,
    run_id: str,
    case_id: str,
    api_port: int,
    blob_root: Path,
) -> dict[str, str]:
    environment = dict(base)
    environment.update(
        {
            "MILAI_TENANT_ID": str(uuid5(NAMESPACE_URL, f"{run_id}:{case_id}:tenant")),
            "MILAI_LOCAL_ACTOR_ID": str(
                uuid5(NAMESPACE_URL, f"{run_id}:{case_id}:actor")
            ),
            "MILAI_BIND_PORT": str(api_port),
            "MILAI_BASE_URL": f"http://127.0.0.1:{api_port}",
            "MILAI_BLOB_ROOT": str(blob_root),
            "MILAI_DATA_MODE": "DEIDENTIFIED_ALLOWED",
        }
    )
    return environment


def _case_project(case_id: str) -> str:
    return f"p10-{hashlib.sha256(case_id.encode()).hexdigest()[:16]}"


def _query(record: Mapping[str, Any]) -> str:
    return (
        f"Reference date: {record['question_date']}\n"
        f"Question: {record['question']}"
    )


def _operational_reference_time(source_snapshot_as_of: str) -> str:
    try:
        parsed = datetime.fromisoformat(source_snapshot_as_of.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Product10RunError("source snapshot is not an RFC3339 timestamp") from exc
    if parsed.utcoffset() is None:
        raise Product10RunError("source snapshot must include a timezone offset")
    return parsed.isoformat()


def _capture_one_case(
    *,
    run_id: str,
    case_id: str,
    record: Mapping[str, Any],
    base_environment: Mapping[str, str],
    work_root: Path,
    capture_workers: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    case_root = work_root / "capture" / case_id
    case_root.mkdir(parents=True, exist_ok=True)
    environment = _case_environment(
        base_environment,
        run_id=run_id,
        case_id=case_id,
        api_port=p09._free_port(),
        blob_root=case_root / "blobs",
    )
    processes = p09.ProcessGroup(case_root)
    try:
        p09._start_runtime(processes, environment)
        events, _, _ = p09_lme._history_events(
            record,
            _case_project(case_id),
            {"selections": []},
        )
        outbox_ids = p09_lme._capture_case(
            environment,
            events,
            workers=capture_workers,
        )
        readiness = _wait_projection_batches(environment, outbox_ids)
        return {
            "status": "CAPTURED",
            "case_id": case_id,
            "event_count": len(events),
            "outbox_count": len(outbox_ids),
            "projection_status": readiness.get("status"),
            "tenant_scope_digest": canonical_sha256(environment["MILAI_TENANT_ID"]),
            "project": _case_project(case_id),
            "environment": environment,
            "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
        }
    except Exception as exc:
        return {
            "status": "CAPTURE_FAILED",
            "case_id": case_id,
            "failure": {"type": type(exc).__name__, "message": _redact(exc)},
            "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
        }
    finally:
        processes.stop()


def _wait_projection_batches(
    environment: dict[str, str], outbox_ids: Sequence[str]
) -> dict[str, Any]:
    if not outbox_ids:
        raise Product10RunError("capture produced no outbox identity")
    batch_count = 0
    last: dict[str, Any] = {}
    for start in range(0, len(outbox_ids), 512):
        last = p09._wait_projection(environment, list(outbox_ids[start : start + 512]))
        batch_count += 1
    return {
        **last,
        "target_count": len(outbox_ids),
        "readiness_batch_count": batch_count,
    }


def _run_testkit(
    *,
    run_id: str,
    case_id: str,
    record: Mapping[str, Any],
    environment: Mapping[str, str],
    source_snapshot_as_of: str,
    arm: str,
) -> tuple[dict[str, Any], float]:
    payload = {
        "schema_version": "milai-retrieval-trace-testkit-request-v0.1",
        "run_identity": f"{run_id}:{case_id}:{arm}",
        "source_snapshot_as_of": source_snapshot_as_of,
        "memory_request": {
            "query": _query(record),
            "invocation_mode": "EXPLICIT_READ",
            "requested_scope": {"project_ids": [_case_project(case_id)]},
            "required_authority": "INFORMATIONAL",
            "required_freshness": "CURRENT",
            "consistency_mode": "CANONICAL_REQUIRED",
            # X1 audits the current query-only agent-memory path.  The question date
            # remains query material; the Host-owned replay boundary is the sealed
            # source snapshot shared with MCP below.
            "reference_time": _operational_reference_time(source_snapshot_as_of),
            "budget": BUDGET,
        },
    }
    started = time.perf_counter()
    completed = subprocess.run(  # noqa: S603 -- pinned Product testkit executable
        [str(TRACE_TESTKIT_EXE)],
        cwd=RUNTIME,
        env=p09._clean_environment(dict(environment)),
        input=json.dumps(payload, ensure_ascii=False).encode(),
        capture_output=True,
        check=False,
        timeout=240,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1_000, 3)
    if completed.returncode != 0:
        raise Product10RunError(
            "Product trace testkit failed: "
            + _redact(completed.stderr.decode(errors="replace"))
        )
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise Product10RunError("Product trace testkit emitted invalid JSON") from exc
    if not isinstance(report, dict):
        raise Product10RunError("Product trace testkit report is not an object")
    _validate_testkit_report(report, run_id=run_id, case_id=case_id, arm=arm)
    return report, elapsed_ms


def _validate_testkit_report(
    report: Mapping[str, Any], *, run_id: str, case_id: str, arm: str
) -> None:
    if (
        report.get("schema_version") != "milai-retrieval-trace-testkit-report-v0.1"
        or report.get("run_identity") != f"{run_id}:{case_id}:{arm}"
    ):
        raise Product10RunError("Product trace testkit identity drifted")
    invariants = report.get("invariants")
    expected = {
        "normal_baseline_traced_response_equal": True,
        "baseline_traced_observer_semantics_equal": True,
        "baseline_traced_repository_calls_equal": True,
        "label_fields_present": False,
        "raw_evidence_text_emitted": False,
        "context_mutation_performed": False,
        "canonical_mutation": False,
        "reader_calls": 0,
        "generative_provider_calls": 0,
        "automatic_retries": 0,
    }
    if not isinstance(invariants, Mapping) or any(
        invariants.get(key) != value for key, value in expected.items()
    ):
        raise Product10RunError("Product trace behavior-neutrality gate failed")
    if {"expected_answer", "acceptable_turn_refs", "instance_groups"}.intersection(
        _recursive_keys(report)
    ):
        raise Product10RunError("Product trace contains scorer-only labels")


async def _mcp_call(url: str, token: str, query: str) -> dict[str, Any]:
    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    ) as http_client:
        async with Client(
            streamable_http_client(url, http_client=http_client),
            mode="2026-07-28",
        ) as client:
            tools = await client.list_tools()
            if [tool.name for tool in tools.tools] != ["milai_memory_resolve"]:
                raise Product10RunError("MCP tool surface drifted")
            result = await client.call_tool("milai_memory_resolve", {"query": query})
            if result.is_error is not False or not isinstance(result.structured_content, dict):
                raise Product10RunError("MCP memory resolve did not return structured content")
            return dict(result.structured_content)


def _sanitize_mcp(value: Mapping[str, Any]) -> dict[str, Any]:
    raw_evidence = value.get("evidence")
    evidence_rows = raw_evidence if isinstance(raw_evidence, list) else []
    evidence: list[dict[str, Any]] = []
    visible_tokens = 0
    for item in evidence_rows:
        if not isinstance(item, Mapping):
            continue
        source = item.get("source")
        source_map = source if isinstance(source, Mapping) else {}
        text = item.get("text")
        if isinstance(text, str):
            visible_tokens += max(1, len(text.split()))
        evidence.append(
            {
                "id": item.get("id"),
                "kind": item.get("kind"),
                "evidence_ids": _strings(item.get("evidence_ids")),
                "source": {
                    "type": source_map.get("type"),
                    "id": source_map.get("id"),
                    "turn_refs": _strings(source_map.get("turn_refs")),
                },
                "observed_at": item.get("observed_at"),
                "text_sha256": hashlib.sha256(text.encode()).hexdigest()
                if isinstance(text, str)
                else None,
            }
        )
    result = {
        "schema_version": value.get("schema_version"),
        "retrieval_status": value.get("retrieval_status"),
        "context_id_present": isinstance(value.get("context_id"), str),
        "snapshot": value.get("snapshot"),
        "continuation": value.get("continuation"),
        "evidence": evidence,
        "warnings": value.get("warnings"),
        "profile": value.get("profile"),
        "visible_token_estimate": visible_tokens,
        "response_sha256": canonical_sha256(value),
        "raw_evidence_text_emitted": False,
    }
    if "text" in _recursive_keys(result):
        raise Product10RunError("MCP redaction retained raw Evidence text")
    return result


def _strings(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _mcp_identities(value: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    evidence_ids: list[str] = []
    turn_refs: list[str] = []
    rows = value.get("evidence")
    if not isinstance(rows, list):
        return evidence_ids, turn_refs
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        evidence_ids.extend(_strings(item.get("evidence_ids")))
        source = item.get("source")
        if isinstance(source, Mapping):
            turn_refs.extend(_strings(source.get("turn_refs")))
    return list(dict.fromkeys(evidence_ids)), list(dict.fromkeys(turn_refs))


def _trace_identities(report: Mapping[str, Any]) -> dict[str, list[str]]:
    trace = report.get("product_trace")
    if not isinstance(trace, Mapping):
        raise Product10RunError("Product trace body is absent")
    raw_evidence: list[str] = []
    raw_turns: list[str] = []
    occurrences = trace.get("occurrences")
    for item in occurrences if isinstance(occurrences, list) else []:
        if not isinstance(item, Mapping):
            continue
        identity = item.get("evidence_record_identity")
        if not isinstance(identity, Mapping):
            continue
        if isinstance(identity.get("evidence_id"), str):
            raw_evidence.append(str(identity["evidence_id"]))
        if isinstance(identity.get("source_ref"), str):
            raw_turns.append(str(identity["source_ref"]))
    post_evidence: list[str] = []
    post_turns: list[str] = []
    candidates = trace.get("candidates")
    for item in candidates if isinstance(candidates, list) else []:
        if not isinstance(item, Mapping):
            continue
        identity = item.get("evidence_record_identity")
        if not isinstance(identity, Mapping):
            continue
        if isinstance(identity.get("evidence_id"), str):
            post_evidence.append(str(identity["evidence_id"]))
        if isinstance(identity.get("source_ref"), str):
            post_turns.append(str(identity["source_ref"]))
    context = report.get("context_admission")
    if not isinstance(context, Mapping):
        raise Product10RunError("Product Context admission trace is absent")
    return {
        "raw_evidence_ids": list(dict.fromkeys(raw_evidence)),
        "raw_turn_refs": list(dict.fromkeys(raw_turns)),
        "post_identity_evidence_ids": list(dict.fromkeys(post_evidence)),
        "post_identity_turn_refs": list(dict.fromkeys(post_turns)),
        "admitted_evidence_ids": _strings(context.get("selected_evidence_ids")),
        "admitted_turn_refs": _strings(context.get("selected_source_turn_refs")),
    }


def _join_matches(report: Mapping[str, Any], mcp: Mapping[str, Any]) -> bool:
    expected = report.get("mcp_join_expectation")
    if not isinstance(expected, Mapping):
        return False
    expected_evidence = _strings(expected.get("selected_evidence_ids"))
    expected_turns = _strings(expected.get("selected_source_turn_refs"))
    observed_evidence, observed_turns = _mcp_identities(mcp)
    return expected_evidence == observed_evidence and expected_turns == observed_turns


def _trace_one_case(
    *,
    run_id: str,
    case_id: str,
    record: Mapping[str, Any],
    environment: Mapping[str, str],
    source_snapshot_as_of: str,
    work_root: Path,
    arm: str = "A0",
) -> dict[str, Any]:
    started = time.perf_counter()
    case_root = work_root / "trace" / arm.casefold() / case_id
    case_root.mkdir(parents=True, exist_ok=True)
    current_environment = _case_environment(
        environment,
        run_id=run_id,
        case_id=case_id,
        api_port=p09._free_port(),
        blob_root=Path(environment["MILAI_BLOB_ROOT"]),
    )
    treatment_enabled = arm == "B1"
    current_environment.update(
        {
            "MILAI_READER_INFORMATIONAL_SOFT_ADMISSION_V0_2_ENABLED": str(
                treatment_enabled
            ).casefold(),
            "MILAI_READER_INSTANCE_PRESERVING_ADMISSION_V0_1_ENABLED": str(
                treatment_enabled
            ).casefold(),
        }
    )
    processes = p09.ProcessGroup(case_root)
    try:
        report, testkit_latency = _run_testkit(
            run_id=run_id,
            case_id=case_id,
            record=record,
            environment=current_environment,
            source_snapshot_as_of=source_snapshot_as_of,
            arm=arm,
        )
        api = processes.start(
            "api",
            [str(p09.API_EXE)],
            cwd=RUNTIME,
            env=p09._clean_environment(current_environment),
        )
        p09._wait_http(f"{current_environment['MILAI_BASE_URL']}/health/ready", api)
        mcp_environment = dict(current_environment)
        mcp_environment["MILAI_AGENT_AS_OF"] = _operational_reference_time(
            source_snapshot_as_of
        )
        mcp_port = p09._free_port()
        inbound_token = secrets.token_urlsafe(40)
        p09._start_mcp(
            processes,
            mcp_environment,
            port=mcp_port,
            inbound_token=inbound_token,
            project=_case_project(case_id),
            name="mcp",
        )
        mcp_started = time.perf_counter()
        raw_mcp = asyncio.run(
            _mcp_call(
                f"http://127.0.0.1:{mcp_port}/mcp",
                inbound_token,
                _query(record),
            )
        )
        mcp_latency = round((time.perf_counter() - mcp_started) * 1_000, 3)
        if raw_mcp.get("schema_version") != "memory-evidence-context-v1":
            raise Product10RunError("MCP renderer schema drifted")
        if raw_mcp.get("profile", {}).get("resolved") != PROFILE:
            raise Product10RunError("MCP budget profile drifted")
        if not _join_matches(report, raw_mcp):
            expected = report.get("mcp_join_expectation")
            expected_map = expected if isinstance(expected, Mapping) else {}
            expected_evidence = _strings(expected_map.get("selected_evidence_ids"))
            expected_turns = _strings(expected_map.get("selected_source_turn_refs"))
            actual_evidence, actual_turns = _mcp_identities(raw_mcp)
            raw_warnings = raw_mcp.get("warnings")
            warning_codes = sorted(
                {
                    str(item["code"])
                    for item in (raw_warnings if isinstance(raw_warnings, list) else [])
                    if isinstance(item, Mapping)
                    and isinstance(item.get("code"), str)
                }
            )
            diagnostic = {
                "retrieval_status": raw_mcp.get("retrieval_status"),
                "warning_codes": warning_codes,
                "snapshot_digest": canonical_sha256(raw_mcp.get("snapshot")),
                "expected_evidence_count": len(expected_evidence),
                "actual_evidence_count": len(actual_evidence),
                "evidence_intersection_count": len(
                    set(expected_evidence).intersection(actual_evidence)
                ),
                "expected_evidence_digest": canonical_sha256(expected_evidence),
                "actual_evidence_digest": canonical_sha256(actual_evidence),
                "expected_turn_count": len(expected_turns),
                "actual_turn_count": len(actual_turns),
                "turn_intersection_count": len(set(expected_turns).intersection(actual_turns)),
                "expected_turn_digest": canonical_sha256(expected_turns),
                "actual_turn_digest": canonical_sha256(actual_turns),
            }
            raise Product10RunError(
                "Product testkit and HTTP MCP identity join diverged "
                + json.dumps(diagnostic, sort_keys=True, separators=(",", ":"))
            )
        sanitized = _sanitize_mcp(raw_mcp)
        identities = _trace_identities(report)
        rendered_evidence, rendered_turns = _mcp_identities(sanitized)
        expected_prefix = f"lme://{hashlib.sha256(case_id.encode()).hexdigest()[:12]}/"
        trace = report["product_trace"]
        candidates = trace.get("candidates", [])
        hydrated = sum(
            bool(item.get("hydrated_span_identities"))
            for item in candidates
            if isinstance(item, Mapping)
        ) if isinstance(candidates, list) else 0
        return {
            "schema_version": "milai-product10-x1-case-trace-v0.1",
            "status": "TRACE_COMPLETE",
            "case_id": case_id,
            "arm": arm,
            "arm_kind": "PRODUCT_TESTKIT_PLUS_PRODUCT_BLACK_BOX",
            "tenant_scope_digest": canonical_sha256(current_environment["MILAI_TENANT_ID"]),
            "project_scope_digest": canonical_sha256(_case_project(case_id)),
            "source_snapshot_as_of": source_snapshot_as_of,
            "query_sha256": canonical_sha256(_query(record)),
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
                "label_fields_present": False,
                "raw_evidence_text_emitted": False,
                "canonical_mutation": False,
                "reader_calls": 0,
                "generative_provider_calls": 0,
                "automatic_semantic_retries": 0,
                "instance_preserving_treatment_enabled": treatment_enabled,
            },
        }
    except Exception as exc:
        return {
            "schema_version": "milai-product10-x1-case-trace-v0.1",
            "status": "TRACE_FAILED",
            "case_id": case_id,
            "arm": arm,
            "failure": {"type": type(exc).__name__, "message": _redact(exc)},
            "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
        }
    finally:
        processes.stop()


def _decisive_step(
    group: InstanceGroup,
    loss: str,
    trace: Mapping[str, Any],
    context_plan_trace: Mapping[str, Any],
) -> dict[str, Any]:
    if loss == "NOT_DISCOVERED":
        channel_rows = trace.get("channel_decisions")
        for row in channel_rows if isinstance(channel_rows, list) else []:
            if isinstance(row, Mapping) and row.get("invocation_disposition") != "INVOKED":
                return {
                    "stage_id": "S12",
                    "reason_code": row.get("reason_code"),
                    "channel": row.get("channel"),
                }
        return {"stage_id": "S12", "reason_code": "REQUIRED_IDENTITY_NOT_RETURNED"}
    if loss == "INSTANCE_DESTROYING_COLLAPSE":
        return {"stage_id": "S21", "reason_code": "STABLE_IDENTITY_REMOVED"}
    if loss == "ADMITTED_NOT_RENDERED":
        return {"stage_id": "M60", "reason_code": "MCP_RENDER_IDENTITY_OMISSION"}
    if loss == "DISCOVERED_NOT_ADMITTED":
        acceptable_evidence = set(group.acceptable_evidence_ids)
        acceptable_turns = set(group.acceptable_turn_refs)
        selected = set(_strings(context_plan_trace.get("selected_unit_ids")))
        raw_render_omissions = context_plan_trace.get("omitted_unit_reasons")
        render_omissions = (
            raw_render_omissions if isinstance(raw_render_omissions, Mapping) else {}
        )
        raw_plan_omissions = context_plan_trace.get("plan_omitted_units")
        plan_omissions = {
            str(item["unit_id"]): item.get("reason")
            for item in (
                raw_plan_omissions if isinstance(raw_plan_omissions, list) else []
            )
            if isinstance(item, Mapping) and isinstance(item.get("unit_id"), str)
        }
        raw_thresholds = context_plan_trace.get("conditional_activation_thresholds")
        thresholds = raw_thresholds if isinstance(raw_thresholds, Mapping) else {}
        raw_envelope = context_plan_trace.get("budget_envelope")
        envelope = raw_envelope if isinstance(raw_envelope, Mapping) else {}
        raw_windows = context_plan_trace.get("candidate_window_trace")
        for window in raw_windows if isinstance(raw_windows, list) else []:
            if not isinstance(window, Mapping) or not isinstance(
                window.get("window_id"), str
            ):
                continue
            evidence_ids = set(_strings(window.get("evidence_ids")))
            turn_refs = set(_strings(window.get("source_turn_refs")))
            if not (
                acceptable_evidence.intersection(evidence_ids)
                or acceptable_turns.intersection(turn_refs)
            ):
                continue
            unit_id = f"evidence:{window['window_id']}"
            if unit_id in selected:
                continue
            return {
                "stage_id": "C50",
                "reason_code": (
                    plan_omissions.get(unit_id)
                    or render_omissions.get(unit_id)
                    or "CONTEXT_UNIT_NOT_ADMITTED"
                ),
                "unit_identity_digest": canonical_sha256(unit_id),
                "source_rank": window.get("source_rank"),
                "activation_threshold": thresholds.get(unit_id),
                "available_memory_tokens": envelope.get("available_memory_tokens"),
            }
        # The identity may have been rejected by Binding/Sufficiency before a
        # Context unit existed.  Continue into the immutable lifecycle trace so
        # C50 is not incorrectly reported as the first-loss boundary.
    lifecycles = trace.get("candidate_lifecycles")
    acceptable_evidence = set(group.acceptable_evidence_ids)
    acceptable_turns = set(group.acceptable_turn_refs)
    occurrence_turns: dict[str, str] = {}
    occurrences = trace.get("occurrences")
    for item in occurrences if isinstance(occurrences, list) else []:
        if not isinstance(item, Mapping):
            continue
        identity = item.get("evidence_record_identity")
        if isinstance(identity, Mapping) and isinstance(item.get("occurrence_id"), str):
            occurrence_turns[str(item["occurrence_id"])] = str(identity.get("source_ref", ""))
    for lifecycle in lifecycles if isinstance(lifecycles, list) else []:
        if not isinstance(lifecycle, Mapping):
            continue
        if (
            lifecycle.get("candidate_identity") not in acceptable_evidence
            and occurrence_turns.get(str(lifecycle.get("occurrence_id"))) not in acceptable_turns
        ):
            continue
        steps = lifecycle.get("lifecycle")
        for step in steps if isinstance(steps, list) else []:
            if not isinstance(step, Mapping):
                continue
            if step.get("disposition") in {"DROPPED", "REJECTED"}:
                return {
                    "stage_id": step.get("stage_id"),
                    "reason_code": step.get("reason_code"),
                    "decision_digest": step.get("decision_digest"),
                }
    return {"stage_id": "C50", "reason_code": "CONTEXT_NOT_ADMITTED"}


def _score_case(trace_row: Mapping[str, Any], label: Mapping[str, Any]) -> dict[str, Any]:
    identity_sets = trace_row.get("identity_sets")
    product_report = trace_row.get("product_testkit")
    if not isinstance(identity_sets, Mapping) or not isinstance(product_report, Mapping):
        raise Product10RunError("cannot score an incomplete Product trace")
    product_trace = product_report.get("product_trace")
    if not isinstance(product_trace, Mapping):
        raise Product10RunError("cannot score an incomplete Product trace")
    raw_context_plan_trace = product_report.get("context_plan_trace")
    context_plan_trace = (
        raw_context_plan_trace if isinstance(raw_context_plan_trace, Mapping) else {}
    )
    groups = tuple(
        InstanceGroup.from_mapping(value)
        for value in label["instance_groups"]
        if isinstance(value, Mapping)
    )
    rendered_evidence = _strings(identity_sets.get("rendered_evidence_ids"))
    rendered_turns = _strings(identity_sets.get("rendered_turn_refs"))
    coverage = distinct_instance_coverage(
        groups,
        visible_evidence_ids=rendered_evidence,
        visible_turn_refs=rendered_turns,
    )
    duplicate = duplicate_instance_rate(
        groups,
        visible_evidence_ids=rendered_evidence,
        visible_turn_refs=rendered_turns,
    )
    group_results: list[dict[str, Any]] = []
    rendered_evidence_set = set(rendered_evidence)
    rendered_turn_set = set(rendered_turns)
    for group in groups:
        loss = first_loss(
            group,
            raw_evidence_ids=_strings(identity_sets.get("raw_evidence_ids")),
            raw_turn_refs=_strings(identity_sets.get("raw_turn_refs")),
            post_identity_evidence_ids=_strings(
                identity_sets.get("post_identity_evidence_ids")
            ),
            post_identity_turn_refs=_strings(identity_sets.get("post_identity_turn_refs")),
            admitted_evidence_ids=_strings(identity_sets.get("admitted_evidence_ids")),
            admitted_turn_refs=_strings(identity_sets.get("admitted_turn_refs")),
            rendered_evidence_ids=rendered_evidence,
            rendered_turn_refs=rendered_turns,
        )
        visibly_covered = bool(
            rendered_evidence_set.intersection(group.acceptable_evidence_ids)
            or rendered_turn_set.intersection(group.acceptable_turn_refs)
        )
        if visibly_covered != (loss is None):
            raise Product10RunError(
                f"coverage/first-loss contradiction for {group.group_id}"
            )
        group_results.append(
            {
                "group_id": group.group_id,
                "covered": visibly_covered,
                "first_loss": loss,
                "decisive_step": _decisive_step(
                    group,
                    loss,
                    product_trace,
                    context_plan_trace,
                )
                if loss is not None
                else None,
            }
        )
    missing = [item for item in group_results if item["first_loss"] is not None]
    frontier_loss = {"INSTANCE_DESTROYING_COLLAPSE", "DISCOVERED_NOT_ADMITTED"}
    opportunity = bool(label["opportunity"]["structural"]) and any(
        item["first_loss"] in frontier_loss for item in missing
    )
    return {
        "schema_version": "milai-product10-x1-scored-case-v0.1",
        "case_id": trace_row["case_id"],
        "arm": trace_row["arm"],
        "capability_shapes": label["capability_shapes"],
        "label_status": {
            "model_assisted_proxy": label["model_assisted_proxy"],
            "human_adjudication_status": label["human_adjudication_status"],
        },
        "distinct_instance_coverage": coverage,
        "duplicate_instance_rate": duplicate,
        "groups": group_results,
        "audited_continuation_opportunity": opportunity,
        "structural_opportunity": bool(label["opportunity"]["structural"]),
    }


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def _summarize_scoring(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    losses: Counter[str] = Counter()
    capability_gain_opportunities: Counter[str] = Counter()
    numerator = 0
    denominator = 0
    full = 0
    opportunities = 0
    for row in rows:
        coverage = row["distinct_instance_coverage"]
        numerator += int(coverage["numerator"])
        denominator += int(coverage["denominator"])
        full += coverage["value"] == 1.0
        opportunities += bool(row["audited_continuation_opportunity"])
        for group in row["groups"]:
            if group["first_loss"] is not None:
                losses[str(group["first_loss"])] += 1
        if row["audited_continuation_opportunity"]:
            capability_gain_opportunities.update(str(value) for value in row["capability_shapes"])
    admission_losses = losses["INSTANCE_DESTROYING_COLLAPSE"] + losses[
        "DISCOVERED_NOT_ADMITTED"
    ]
    return {
        "case_count": len(rows),
        "distinct_instance_coverage_micro": {
            "numerator": numerator,
            "denominator": denominator,
            "value": numerator / denominator if denominator else 0.0,
        },
        "mean_distinct_instance_coverage": sum(
            float(row["distinct_instance_coverage"]["value"]) for row in rows
        )
        / len(rows)
        if rows
        else 0.0,
        "full_coverage_cases": full,
        "first_loss_counts": dict(sorted(losses.items())),
        "audited_continuation_opportunity_cases": opportunities,
        "opportunity_capability_shapes": dict(sorted(capability_gain_opportunities.items())),
        "x2_b1_decision": (
            "REQUIRED_BY_ADMISSION_OR_COLLAPSE_FIRST_LOSS"
            if admission_losses
            else "NOT_NEEDED_FOR_OBSERVED_FIRST_LOSSES"
        ),
        "x3_decision": "READY_FOR_B2" if opportunities >= 6 else "INSUFFICIENT_OPPORTUNITY",
    }


def _matched_candidate_pool_receipt(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    by_arm = {
        arm: {str(row["case_id"]): row for row in rows if row.get("arm") == arm}
        for arm in ("A0", "B1")
    }
    case_ids = sorted(set(by_arm["A0"]).intersection(by_arm["B1"]))
    mismatches: list[str] = []
    material: list[dict[str, Any]] = []
    for case_id in case_ids:
        left = by_arm["A0"][case_id]
        right = by_arm["B1"][case_id]
        left_ids = left.get("identity_sets")
        right_ids = right.get("identity_sets")
        left_counts = left.get("counts")
        right_counts = right.get("counts")
        if not isinstance(left_ids, Mapping) or not isinstance(right_ids, Mapping):
            mismatches.append(case_id)
            continue
        identity_fields = (
            "raw_evidence_ids",
            "raw_turn_refs",
            "post_identity_evidence_ids",
            "post_identity_turn_refs",
        )
        identity_equal = all(left_ids.get(key) == right_ids.get(key) for key in identity_fields)
        counts_equal = (
            isinstance(left_counts, Mapping)
            and isinstance(right_counts, Mapping)
            and all(
                left_counts.get(key) == right_counts.get(key)
                for key in ("scanned_occurrences", "unique_evidence", "hydrated_units")
            )
        )
        envelope_equal = (
            left.get("query_sha256") == right.get("query_sha256")
            and left.get("source_snapshot_as_of") == right.get("source_snapshot_as_of")
            and left.get("tenant_scope_digest") == right.get("tenant_scope_digest")
            and left.get("project_scope_digest") == right.get("project_scope_digest")
        )
        if not (identity_equal and counts_equal and envelope_equal):
            mismatches.append(case_id)
        material.append(
            {
                "case_id": case_id,
                "raw_evidence_ids": left_ids.get("raw_evidence_ids"),
                "raw_turn_refs": left_ids.get("raw_turn_refs"),
                "post_identity_evidence_ids": left_ids.get(
                    "post_identity_evidence_ids"
                ),
                "post_identity_turn_refs": left_ids.get("post_identity_turn_refs"),
            }
        )
    return {
        "schema_version": "milai-product10-matched-candidate-pool-receipt-v0.1",
        "case_count": len(case_ids),
        "same_candidate_pool": len(case_ids) == 24 and not mismatches,
        "mismatch_case_ids": mismatches,
        "candidate_pool_digest": canonical_sha256(material),
    }


def _summarize_h1(
    a0_rows: Sequence[Mapping[str, Any]],
    b1_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    a0 = {str(row["case_id"]): row for row in a0_rows}
    b1 = {str(row["case_id"]): row for row in b1_rows}
    case_ids = sorted(set(a0).intersection(b1))
    gains: list[str] = []
    losses: list[str] = []
    full_coverage_case_losses: list[str] = []
    gain_cases: set[str] = set()
    paired_gains: list[float] = []
    for case_id in case_ids:
        left = a0[case_id]
        right = b1[case_id]
        paired_gains.append(
            float(right["distinct_instance_coverage"]["value"])
            - float(left["distinct_instance_coverage"]["value"])
        )
        left_coverage = left["distinct_instance_coverage"]
        right_coverage = right["distinct_instance_coverage"]
        if (
            int(left_coverage["numerator"]) == int(left_coverage["denominator"])
            and int(right_coverage["numerator"]) < int(right_coverage["denominator"])
        ):
            full_coverage_case_losses.append(case_id)
        left_groups = {str(row["group_id"]): bool(row["covered"]) for row in left["groups"]}
        right_groups = {
            str(row["group_id"]): bool(row["covered"]) for row in right["groups"]
        }
        for group_id in sorted(set(left_groups).intersection(right_groups)):
            if not left_groups[group_id] and right_groups[group_id]:
                gains.append(group_id)
                gain_cases.add(case_id)
            elif left_groups[group_id] and not right_groups[group_id]:
                losses.append(group_id)
    gain_shapes = sorted(
        {
            str(shape)
            for case_id in gain_cases
            for shape in b1[case_id]["capability_shapes"]
        }
    )
    mean_gain = sum(paired_gains) / len(paired_gains) if paired_gains else 0.0
    collapse_count = sum(
        group.get("first_loss") == "INSTANCE_DESTROYING_COLLAPSE"
        for row in b1_rows
        for group in row["groups"]
    )
    passed = (
        len(case_ids) == 24
        and mean_gain >= 0.05
        and len(gains) >= 2
        and len(gain_shapes) >= 2
        and not full_coverage_case_losses
        and collapse_count == 0
    )
    return {
        "schema_version": "milai-product10-h1-matched-effect-v0.2",
        "status": "PASS_PRODUCT10_H1" if passed else "FAIL_PRODUCT10_H1",
        "paired_case_count": len(case_ids),
        "mean_distinct_instance_coverage_gain": mean_gain,
        "newly_covered_instance_groups": len(gains),
        "newly_covered_group_ids": gains,
        "gain_capability_shape_count": len(gain_shapes),
        "gain_capability_shapes": gain_shapes,
        "previously_covered_instance_groups_lost": len(losses),
        "lost_group_ids": losses,
        "previously_full_coverage_cases_lost": len(full_coverage_case_losses),
        "lost_full_coverage_case_ids": full_coverage_case_losses,
        "cross_evidence_hard_collapse_count": collapse_count,
        "thresholds": {
            "mean_gain_gte": 0.05,
            "new_groups_gte": 2,
            "gain_shapes_gte": 2,
            "previously_full_coverage_cases_lost_eq": 0,
            "hard_collapse_eq": 0,
        },
    }


def _command_material(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "runner": "tools/run_product10_context.py",
        "run_id": args.run_id,
        "arm": "A0_B1_MATCHED" if args.paired_b1 else "A0",
        "paired_b1": args.paired_b1,
        "output": str(args.output.resolve()),
        "dataset_manifest": str(args.dataset_manifest.resolve()),
        "membership": str(args.membership.resolve()),
        "instance_labels": str(args.instance_labels.resolve()),
        "product_lock": str(args.product_lock.resolve()),
        "capture_workers": args.capture_workers,
        "case_concurrency": args.case_concurrency,
        "profile": PROFILE,
        "budget": BUDGET,
    }


def _cleanup_receipt(compose: Sequence[str], compose_project: str) -> dict[str, Any]:
    down = p09._command(
        [*compose, "down", "--volumes", "--remove-orphans"],
        cwd=RUNTIME,
        timeout=120,
        check=False,
    )
    containers = p09._command(
        ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={compose_project}"],
        timeout=30,
        check=False,
    )
    volumes = p09._command(
        [
            "docker",
            "volume",
            "ls",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={compose_project}",
        ],
        timeout=30,
        check=False,
    )
    return {
        "schema_version": "milai-product10-cleanup-receipt-v0.1",
        "compose_project": compose_project,
        "down_returncode": down.returncode,
        "remaining_container_ids": [line for line in containers.stdout.splitlines() if line],
        "remaining_volume_names": [line for line in volumes.stdout.splitlines() if line],
        "run_owned_database_volume_removed": (
            down.returncode == 0 and not containers.stdout.strip() and not volumes.stdout.strip()
        ),
        "stderr": _redact(down.stderr),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    started_at = datetime.now(UTC).isoformat()
    arms = ("A0", "B1") if args.paired_b1 else ("A0",)
    run_arm = "A0_B1_MATCHED" if args.paired_b1 else "A0"
    args.output.mkdir(parents=True, exist_ok=False)
    membership = _load_membership(args.membership)
    population = _load_population(args.dataset_manifest, membership)
    expected_label_sha = str(membership["source_label_seal_sha256"])
    if _sha256_file(args.instance_labels) != expected_label_sha:
        raise Product10RunError("instance label file does not match membership preseal")
    lock = load_product_lock(args.product_lock)
    lock_verification = verify_product_lock(lock, PRODUCT)
    if not lock_verification.valid:
        raise Product10RunError(
            "Product behavior lock verification failed: " + "; ".join(lock_verification.errors)
        )
    for executable in (
        p09.OPS_EXE,
        p09.ALEMBIC_EXE,
        p09.API_EXE,
        p09.WORKER_EXE,
        p09.MCP_EXE,
        p09.HOOK_EXE,
        TRACE_TESTKIT_EXE,
        args.codex,
    ):
        if not executable.is_file():
            raise Product10RunError(f"required executable is missing: {executable}")
    codex_version = p09._command([str(args.codex), "--version"], timeout=15).stdout.strip()
    codex_identity = {**CODEX_IDENTITY, "cli_version": codex_version}
    codex_config_digest = canonical_sha256(codex_identity)
    command = _command_material(args)
    command_sha256 = canonical_sha256(command)
    runner_sha256 = _sha256_file(Path(__file__).resolve())
    preseal = {
        "schema_version": "milai-product10-run-preseal-v0.1",
        "run_identity": args.run_id,
        "arm": run_arm,
        "sealed_at": started_at,
        "product_tree_sha256": lock.tree_sha256,
        "product_lock_digest": lock.digest,
        "lab_runner_sha256": runner_sha256,
        "command": command,
        "command_sha256": command_sha256,
        "dataset_sha256": membership["dataset_sha256"],
        "dataset_manifest_sha256": membership["dataset_manifest_sha256"],
        "selection_sha256": _sha256_file(args.membership),
        "case_order_sha256": membership["case_order_sha256"],
        "instance_label_sha256": expected_label_sha,
        "label_provenance": "Qwen3.6-35B-A3B-FP8 model-assisted proxy",
        "label_adjudication_status": "PENDING",
        "codex_provider": codex_identity["provider"],
        "codex_model": codex_identity["model"],
        "codex_cli_version": codex_identity["cli_version"],
        "codex_config_digest": codex_config_digest,
        "profile": PROFILE,
        "formal_files_accessed": True,
        "formal_cases_scored": 0,
        "labels_loaded_for_product_trace": False,
    }
    _write_json(args.output / "preseal.json", preseal)

    postgres_port = p09._free_port()
    bootstrap_port = p09._free_port()
    compose_project = f"{args.run_id}-pg"
    trace_rows: list[dict[str, Any]] = []
    capture_rows: list[dict[str, Any]] = []
    scoring_rows: list[dict[str, Any]] = []
    failure: dict[str, Any] | None = None
    cleanup: dict[str, Any]
    database_before: dict[str, int] | None = None
    database_after: dict[str, int] | None = None
    source_snapshot = ""
    with tempfile.TemporaryDirectory(prefix="milai-p10-context-") as temporary:
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
                    raise Product10RunError("fresh PostgreSQL migration did not become ready")
                time.sleep(1)
            database_before = p09._database_counts(compose)
            for case_id in membership["case_ids"]:
                capture = _capture_one_case(
                    run_id=args.run_id,
                    case_id=str(case_id),
                    record=population[str(case_id)],
                    base_environment=base_environment,
                    work_root=work_root,
                    capture_workers=args.capture_workers,
                )
                capture_rows.append(capture)
            _write_jsonl(
                args.output / "capture-trace.jsonl",
                [
                    {key: value for key, value in row.items() if key != "environment"}
                    for row in capture_rows
                ],
            )
            failed_capture = [row for row in capture_rows if row["status"] != "CAPTURED"]
            if failed_capture:
                raise Product10RunError(f"{len(failed_capture)} cases failed capture")
            source_snapshot = datetime.now(UTC).isoformat()

            by_capture = {str(row["case_id"]): row for row in capture_rows}

            def observe(case_id: str, arm: str) -> dict[str, Any]:
                capture = by_capture[case_id]
                return _trace_one_case(
                    run_id=args.run_id,
                    case_id=case_id,
                    record=population[case_id],
                    environment=capture["environment"],
                    source_snapshot_as_of=source_snapshot,
                    work_root=work_root,
                    arm=arm,
                )

            for arm in arms:
                with ThreadPoolExecutor(max_workers=args.case_concurrency) as executor:
                    arm_rows = list(
                        executor.map(
                            lambda case_id, current_arm=arm: observe(
                                case_id, current_arm
                            ),
                            [str(value) for value in membership["case_ids"]],
                        )
                    )
                trace_rows.extend(arm_rows)
            _write_jsonl(args.output / "product-trace.redacted.jsonl", trace_rows)
            failed_trace = [row for row in trace_rows if row["status"] != "TRACE_COMPLETE"]
            if failed_trace:
                raise Product10RunError(f"{len(failed_trace)} cases failed Product/MCP tracing")
            matched_candidate_pool = (
                _matched_candidate_pool_receipt(trace_rows)
                if args.paired_b1
                else None
            )
            if (
                matched_candidate_pool is not None
                and matched_candidate_pool["same_candidate_pool"] is not True
            ):
                raise Product10RunError("A0/B1 candidate pool or read envelope diverged")

            # Anti-leakage boundary: scorer-only labels are parsed only after the complete,
            # immutable Product/MCP trace has been written.
            labels = _load_labels(args.instance_labels, expected_label_sha)
            scoring_rows = [
                _score_case(row, labels[str(row["case_id"])]) for row in trace_rows
            ]
            _write_jsonl(args.output / "scoring-view.jsonl", scoring_rows)
            database_after = p09._database_counts(compose)
            if database_after["canonical"] != database_before["canonical"]:
                raise Product10RunError("Context recall mutated Canonical tables")
            if any(
                row["invariants"]["cross_namespace_source_count"] != 0
                for row in trace_rows
            ):
                raise Product10RunError("Context arm returned a cross-case source identity")
        except Exception as exc:
            failure = {"type": type(exc).__name__, "message": _redact(exc)}
        finally:
            cleanup = _cleanup_receipt(compose, compose_project)

    _write_json(args.output / "cleanup-receipt.json", cleanup)
    trace_path = args.output / "product-trace.redacted.jsonl"
    capture_path = args.output / "capture-trace.jsonl"
    scoring_path = args.output / "scoring-view.jsonl"
    cleanup_path = args.output / "cleanup-receipt.json"
    scoring_by_arm = {
        arm: _summarize_scoring(
            [row for row in scoring_rows if row.get("arm") == arm]
        )
        for arm in arms
    }
    scoring_summary: dict[str, Any] = (
        {
            "by_arm": scoring_by_arm,
            "h1": _summarize_h1(
                [row for row in scoring_rows if row.get("arm") == "A0"],
                [row for row in scoring_rows if row.get("arm") == "B1"],
            ),
        }
        if args.paired_b1
        else scoring_by_arm["A0"]
    )
    latencies = [
        float(row["latency_ms"]["http_mcp"])
        for row in trace_rows
        if row.get("status") == "TRACE_COMPLETE" and isinstance(row.get("latency_ms"), Mapping)
    ]
    valid = (
        failure is None
        and len(trace_rows) == 24 * len(arms)
        and len(scoring_rows) == 24 * len(arms)
        and all(sum(row.get("arm") == arm for row in trace_rows) == 24 for arm in arms)
        and all(row.get("status") == "TRACE_COMPLETE" for row in trace_rows)
        and database_before is not None
        and database_after is not None
        and database_after["canonical"] == database_before["canonical"] == 0
        and cleanup["run_owned_database_volume_removed"] is True
    )
    summary = {
        "schema_version": "milai-product10-context-effect-summary-v0.2",
        "status": (
            "PASS_PRODUCT10_X2_A0_B1_MATCHED"
            if valid and args.paired_b1
            else "PASS_PRODUCT10_X1_A0_TRACED"
            if valid
            else "FAIL_PRODUCT10_CONTEXT_RUN_INVALID"
        ),
        "run_identity": args.run_id,
        "arm": run_arm,
        "source_snapshot_as_of": source_snapshot or None,
        "case_count": len(trace_rows),
        "scored_case_count": len(scoring_rows),
        "capture_case_count": len(capture_rows),
        "capture_event_count": sum(int(row.get("event_count", 0)) for row in capture_rows),
        "scoring": scoring_summary,
        "latency_ms": {
            "http_mcp_p50": _percentile(latencies, 0.50),
            "http_mcp_p95": _percentile(latencies, 0.95),
        },
        "database_counts_before": database_before,
        "database_counts_after": database_after,
        "invariants": {
            "fresh_postgresql": True,
            "isolated_tenant_per_case": len(
                {
                    row.get("tenant_scope_digest")
                    for row in trace_rows
                    if row.get("status") == "TRACE_COMPLETE"
                }
            )
            == len(capture_rows),
            "matched_candidate_pool": (
                _matched_candidate_pool_receipt(trace_rows)
                if args.paired_b1 and trace_rows
                else None
            ),
            "trace_written_before_labels_loaded": bool(trace_rows),
            "formal_files_accessed": True,
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
            "run_owned_database_volume_removed": cleanup[
                "run_owned_database_volume_removed"
            ],
        },
        "failure": failure,
        "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
    }
    _write_json(args.output / "summary.json", summary)
    run_bundle = {
        **preseal,
        "schema_version": "milai-product10-run-bundle-v0.1",
        "source_snapshot_as_of": source_snapshot or None,
        "projection_identity": {
            "kind": "evidence-search-v1",
            "capture_event_count": summary["capture_event_count"],
            "database_projection_count": database_after["projection"]
            if database_after is not None
            else None,
        },
        "redacted_trace_sha256": _sha256_file(trace_path) if trace_path.is_file() else None,
        "capture_trace_sha256": _sha256_file(capture_path) if capture_path.is_file() else None,
        "scoring_view_sha256": _sha256_file(scoring_path) if scoring_path.is_file() else None,
        "cleanup_receipt_sha256": _sha256_file(cleanup_path),
        "summary_sha256": _sha256_file(args.output / "summary.json"),
        "formal_files_accessed": True,
        "formal_cases_scored": 0,
        "run_valid": valid,
    }
    _write_json(args.output / "run-bundle.json", run_bundle)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, default=DEFAULT_DATASET_MANIFEST)
    parser.add_argument("--membership", type=Path, default=DEFAULT_MEMBERSHIP)
    parser.add_argument("--instance-labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--product-lock", type=Path, default=DEFAULT_PRODUCT_LOCK)
    parser.add_argument("--capture-workers", type=int, default=8)
    parser.add_argument("--case-concurrency", type=int, default=4)
    parser.add_argument(
        "--paired-b1",
        action="store_true",
        help="run A0 and B1 against the same captured candidate identities and snapshot",
    )
    parser.add_argument(
        "--codex",
        type=Path,
        default=Path(os.environ.get("CODEX_BIN", "/root/.local/bin/codex")),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not _RUN_ID.fullmatch(args.run_id):
        raise SystemExit("run-id must contain 8-48 lowercase alphanumeric/hyphen characters")
    if args.output.exists():
        raise SystemExit("output already exists")
    if not 1 <= args.capture_workers <= 8:
        raise SystemExit("capture-workers must be 1..8")
    if not 1 <= args.case_concurrency <= 8:
        raise SystemExit("case-concurrency must be 1..8")
    try:
        summary = run(args)
    except Exception as exc:
        print(
            f"Product-10 A0 failed before run artifact initialization: "
            f"{type(exc).__name__}: {_redact(exc)}",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["status"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
