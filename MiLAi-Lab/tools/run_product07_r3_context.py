#!/usr/bin/env python3
"""Run the frozen Product-07 R3 slice through Context-only A/B0/B1 arms.

Each case is captured once into an independent real PostgreSQL tenant.  The same
Evidence namespace is then resolved through the current path (A), simple
query-preserving recall (B0), and same-pool soft EvidenceSet selection (B1).
No answer Provider, OpenWorker answer, or Judge is invoked by this runner.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import secrets
import shutil
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from milai_lab.product_adapter.manifest import load_product_lock, verify_product_lock
from run_product05_openworker_lme import (
    ALEMBIC_EXE,
    API_EXE,
    BROKER_EXE,
    LAB,
    MCP_EXE,
    MODEL,
    OPS_EXE,
    PRODUCT,
    RUNTIME,
    SCOPE_PROJECT,
    WORKER_EXE,
    ManagedProcesses,
    _broker_resolve,
    _capture,
    _clean_environment,
    _command,
    _database_audit,
    _free_port,
    _history_events,
    _load_environment,
    _load_inputs,
    _policy,
    _retrieval_metrics,
    _sha256_file,
    _sha256_text,
    _wait_http,
    _wait_projection,
    _wait_socket,
)
from run_product07_context_replay import (
    _canonical_sha256,
    _receipt_sources,
    _trace_summary,
    _write_json,
    _write_jsonl,
)

DEFAULT_SELECTION = LAB / "data/labels/product06-reader-selection.v0.1.json"
DEFAULT_SOURCE_SELECTION = LAB / "data/labels/product03-context24-selection.v0.1.json"
DEFAULT_LABELS = LAB / "data/labels/product02-longmemeval-answer-turns-qwen36-v4.json"
DEFAULT_MANIFEST = LAB / "data/manifests/longmemeval-s-cleaned-500.json"
DEFAULT_LOCK = LAB / "data/locks/product07-product-s2-b1.lock.json"
DEFAULT_V0_RUN = LAB / "var/product07/s2-v0-b1-r2"
ARMS = ("A", "B0", "B1")


class Product07R3ContextError(RuntimeError):
    pass


@dataclass(slots=True)
class ContextCase:
    ordinal: int
    metadata: dict[str, Any]
    record: dict[str, Any]
    root: Path
    environment: dict[str, str]


def _load_labels(path: Path, case_ids: Sequence[str]) -> dict[str, Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("cases") if isinstance(payload, Mapping) else None
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != "milai-product02-answer-turn-labels-v1"
        or not isinstance(rows, list)
    ):
        raise Product07R3ContextError("answer-turn label artifact is invalid")
    labels = {
        str(value["case_id"]): value
        for value in rows
        if isinstance(value, Mapping) and isinstance(value.get("case_id"), str)
    }
    if len(labels) != len(rows) or any(case_id not in labels for case_id in case_ids):
        raise Product07R3ContextError("frozen R3 answer-turn labels are incomplete")
    return labels


def _make_case(
    *,
    ordinal: int,
    metadata: dict[str, Any],
    record: dict[str, Any],
    scratch: Path,
    base_environment: Mapping[str, str],
) -> ContextCase:
    root = scratch / f"c{ordinal:02d}"
    root.mkdir(mode=0o700)
    (root / "blobs").mkdir(mode=0o700)
    environment = dict(base_environment)
    environment.update(
        {
            "MILAI_BLOB_ROOT": str(root / "blobs"),
            "MILAI_TENANT_ID": str(uuid4()),
            "MILAI_LOCAL_ACTOR_ID": str(uuid4()),
            "MILAI_API_TOKEN": secrets.token_urlsafe(48),
            "MILAI_CAUSAL_TOKEN_SECRET": secrets.token_urlsafe(48),
            "MILAI_AGENT_READER_TOKEN": secrets.token_urlsafe(48),
            "MILAI_AGENT_SUBMITTER_TOKEN": secrets.token_urlsafe(48),
            "MILAI_AGENT_OPERATOR_TOKEN": secrets.token_urlsafe(48),
            "MILAI_AGENT_REVIEWER_TOKEN": secrets.token_urlsafe(48),
            "MILAI_BLOB_KEK_B64": base64.b64encode(secrets.token_bytes(32)).decode(),
            "MILAI_DATA_MODE": "DEIDENTIFIED_ALLOWED",
        }
    )
    return ContextCase(
        ordinal=ordinal,
        metadata=metadata,
        record=record,
        root=root,
        environment=environment,
    )


async def _capture_case(case: ContextCase, capture_concurrency: int) -> list[dict[str, Any]]:
    environment = dict(case.environment)
    environment.update(
        {
            "MILAI_BIND_PORT": str(_free_port()),
            "MILAI_RETRIEVAL_QUERY_PRESERVING_UNION_ENABLED": "false",
            "MILAI_RETRIEVAL_EVIDENCE_SET_SELECTION_ENABLED": "false",
        }
    )
    environment["MILAI_BASE_URL"] = f"http://127.0.0.1:{environment['MILAI_BIND_PORT']}"
    processes = ManagedProcesses()
    try:
        api = processes.start(
            [str(API_EXE)],
            case.root / "capture-api.log",
            cwd=RUNTIME,
            env=_clean_environment(environment),
        )
        worker = processes.start(
            [str(WORKER_EXE)],
            case.root / "capture-worker.log",
            cwd=RUNTIME,
            env=_clean_environment(environment),
        )
        await asyncio.to_thread(
            _wait_http, f"{environment['MILAI_BASE_URL']}/health/ready", api
        )
        if worker.poll() is not None:
            raise Product07R3ContextError("projection worker exited during capture startup")
        helper_args = SimpleNamespace(
            mcp_executable=MCP_EXE,
            scope_project=SCOPE_PROJECT,
            capture_concurrency=capture_concurrency,
        )
        events = _history_events(case.record, SCOPE_PROJECT)
        receipts = await _capture(helper_args, events, environment)
        await _wait_projection(helper_args, receipts, environment)
        return [dict(value) for value in receipts]
    finally:
        processes.stop_all()


async def _resolve_arm(case: ContextCase, arm: str) -> dict[str, Any]:
    if arm not in ARMS:
        raise Product07R3ContextError(f"unsupported retrieval arm: {arm}")
    arm_root = case.root / arm.casefold()
    arm_root.mkdir(mode=0o700)
    socket_root = arm_root / "reader-lite"
    socket_root.mkdir(mode=0o700)
    socket_path = socket_root / "reader-lite.sock"
    port = _free_port()
    environment = dict(case.environment)
    environment.update(
        {
            "MILAI_BIND_PORT": str(port),
            "MILAI_BASE_URL": f"http://127.0.0.1:{port}",
            "MILAI_RETRIEVAL_QUERY_PRESERVING_UNION_ENABLED": (
                "true" if arm in {"B0", "B1"} else "false"
            ),
            "MILAI_RETRIEVAL_EVIDENCE_SET_SELECTION_ENABLED": (
                "true" if arm == "B1" else "false"
            ),
        }
    )
    policy_path = arm_root / "reader.policy.json"
    token_path = arm_root / "reader.token"
    _write_json(policy_path, _policy(socket_path, environment["MILAI_BASE_URL"]))
    token_path.write_text(environment["MILAI_AGENT_READER_TOKEN"] + "\n", encoding="utf-8")
    token_path.chmod(0o600)
    processes = ManagedProcesses()
    try:
        api = processes.start(
            [str(API_EXE)],
            arm_root / "api.log",
            cwd=RUNTIME,
            env=_clean_environment(environment),
        )
        await asyncio.to_thread(
            _wait_http, f"{environment['MILAI_BASE_URL']}/health/ready", api
        )
        broker = processes.start(
            [
                str(BROKER_EXE),
                "--policy",
                str(policy_path),
                "--token-file",
                str(token_path),
                "--resolve-budget-profile",
                "OPENWORKER_USABILITY_WIDE_V02",
            ],
            arm_root / "broker.log",
        )
        await asyncio.to_thread(_wait_socket, socket_path, broker)
        prompt = (
            f"Reference date: {case.record['question_date']}\n"
            f"{case.record['question']}\n"
            "Answer concisely using only the governed memory supplied for this operation."
        )
        return await asyncio.to_thread(_broker_resolve, socket_path, prompt)
    finally:
        processes.stop_all()


def _arm_result(
    *,
    case: ContextCase,
    arm: str,
    snapshot: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    answer_label: Mapping[str, Any],
) -> dict[str, Any]:
    memory_context = snapshot.get("memory_context")
    if not isinstance(memory_context, Mapping) or not isinstance(
        memory_context.get("text"), str
    ):
        raise Product07R3ContextError(f"{arm} Reader-visible Context is absent")
    selected = memory_context.get("selected_evidence_ids")
    captured_ids = {str(value["evidence_id"]) for value in receipts}
    if (
        not isinstance(selected, list)
        or any(not isinstance(value, str) for value in selected)
        or not set(selected).issubset(captured_ids)
    ):
        raise Product07R3ContextError(f"{arm} selected Evidence identity is invalid")
    source_by_evidence = {
        str(value["evidence_id"]): str(value["source_ref"]) for value in receipts
    }
    selected_refs = {source_by_evidence[value] for value in selected}
    expected_prefix = f"lme://{_sha256_text(str(case.record['question_id']))[:12]}/"
    cross_namespace = sum(not value.startswith(expected_prefix) for value in selected_refs)
    trace = (
        _baseline_trace_summary(memory_context, snapshot)
        if arm == "A"
        else _trace_summary(memory_context, snapshot)
    )
    if trace.get("hidden_model_calls") != 0:
        raise Product07R3ContextError(f"{arm} made a hidden model call")
    raw_receipt = snapshot.get("context_receipt")
    if raw_receipt is None:
        selected_source_refs = memory_context.get("selected_source_turn_refs")
        if selected or selected_source_refs != []:
            raise Product07R3ContextError(
                f"{arm} non-empty Context is missing its receipt"
            )
        receipt_status = "EMPTY_CONTEXT_NO_RECEIPT"
    else:
        receipt_sources = _receipt_sources(snapshot)
        receipt_ids = {value["evidence_id"] for value in receipt_sources}
        if not set(selected).issubset(receipt_ids):
            raise Product07R3ContextError(f"{arm} Context receipt lost selected lineage")
        receipt_status = "PRESENT"
    return {
        "context_sha256": _sha256_text(str(memory_context["text"])),
        "selected_evidence_count": len(selected),
        "selected_source_turn_count": len(selected_refs),
        "selected_source_identity_digest": _canonical_sha256(sorted(selected_refs)),
        "retrieval_metrics": _retrieval_metrics(
            case.record, receipts, selected, answer_label
        ),
        "context_receipt_status": receipt_status,
        "trace": trace,
        "cross_namespace_source_count": cross_namespace,
    }


def _baseline_trace_summary(
    memory_context: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> dict[str, Any]:
    """Normalize the current legacy Context path without inventing B-stage traces."""

    compile_trace = memory_context.get("compile_trace")
    if not isinstance(compile_trace, Mapping):
        raise Product07R3ContextError("A Memory Context compile trace is absent")
    if compile_trace.get("canonical_mutation") is not False:
        raise Product07R3ContextError("A Context path did not prove mutation absence")
    budget = memory_context.get("token_budget")
    if not isinstance(budget, int) or isinstance(budget, bool):
        raise Product07R3ContextError("A Context token budget is invalid")
    search_trace = snapshot.get("search_trace")
    search = search_trace if isinstance(search_trace, Mapping) else {}
    dispositions = search.get("acquisition_probe_dispositions")
    dense = [
        dict(value)
        for value in dispositions
        if isinstance(value, Mapping) and value.get("channel") == "EVIDENCE_DENSE"
    ] if isinstance(dispositions, list) else []
    return {
        "compiler_version": compile_trace.get("compiler_version"),
        "acquired_candidate_count": None,
        "acquired_trace_sha256": None,
        "acquired_ranked_source_turn_sha256s": [],
        "admitted_evidence_count": len(memory_context.get("selected_evidence_ids", [])),
        "admitted_trace_sha256": None,
        "admitted_source_turn_sha256s": sorted(
            _sha256_text(str(value))
            for value in memory_context.get("selected_source_turn_refs", [])
            if isinstance(value, str)
        ),
        "reader_visible_evidence_count": len(
            memory_context.get("selected_evidence_ids", [])
        ),
        "reader_visible_trace_sha256": None,
        "reader_visible_source_turn_sha256s": sorted(
            _sha256_text(str(value))
            for value in memory_context.get("selected_source_turn_refs", [])
            if isinstance(value, str)
        ),
        "selected_window_count": memory_context.get("selected_windows"),
        "available_window_count": memory_context.get("available_windows"),
        "estimated_context_tokens": memory_context.get("estimated_tokens"),
        "context_truncated": memory_context.get("context_truncated"),
        "locality_hydrated_count": compile_trace.get("hydrated_evidence_count", 0),
        "omitted_unit_reasons": None,
        "plan_omitted_units": None,
        "conditional_unit_order": None,
        "selected_conditional_unit_ids": None,
        "candidate_window_trace": [],
        "protected_closure_tokens": None,
        "session_diversity_enabled": compile_trace.get(
            "session_diversity_objective_enabled",
            compile_trace.get("multi_session_requirement"),
        ),
        "query_preserving_union_enabled": False,
        "evidence_set_selection_enabled": False,
        "recall_workspace_trace": None,
        "budget_envelope": {
            "schema_version": "context-budget-envelope-v0.1",
            "requested_cap": budget,
            "available_memory_tokens": budget,
            "budget_source": "LEGACY_CALLER_CAP",
        },
        "dense_dispositions": dense,
        "canonical_mutation": False,
        "hidden_model_calls": compile_trace.get("hidden_model_calls"),
    }


async def _one_case(
    case: ContextCase,
    *,
    answer_label: Mapping[str, Any],
    capture_concurrency: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    receipts = await _capture_case(case, capture_concurrency)
    arms: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        snapshot = await _resolve_arm(case, arm)
        arms[arm] = _arm_result(
            case=case,
            arm=arm,
            snapshot=snapshot,
            receipts=receipts,
            answer_label=answer_label,
        )
    b0_trace = arms["B0"]["trace"]
    b1_trace = arms["B1"]["trace"]
    same_pool = {
        "candidate_set_match": set(b0_trace["acquired_ranked_source_turn_sha256s"])
        == set(b1_trace["acquired_ranked_source_turn_sha256s"]),
        "acquired_order_match": b0_trace["acquired_ranked_source_turn_sha256s"]
        == b1_trace["acquired_ranked_source_turn_sha256s"],
        "window_closure_match": b0_trace["candidate_window_trace"]
        == b1_trace["candidate_window_trace"],
        "hydration_count_match": b0_trace["locality_hydrated_count"]
        == b1_trace["locality_hydrated_count"],
        "effective_budget_match": b0_trace["budget_envelope"]
        == b1_trace["budget_envelope"],
    }
    return {
        "ordinal": case.ordinal,
        "case_id_sha256": _sha256_text(str(case.record["question_id"])),
        "query_sha256": _sha256_text(str(case.record["question"])),
        "query_type": case.metadata.get("query_type"),
        "capability_family": case.metadata.get("capability_family"),
        "ordinary_lookup": case.metadata.get("ordinary_lookup"),
        "source_session_count": len(case.record["haystack_sessions"]),
        "source_turn_count": len(_history_events(case.record, SCOPE_PROJECT)),
        "captured_evidence_count": len(receipts),
        "arms": arms,
        "same_pool": same_pool,
        "status": "PASS"
        if all(same_pool.values())
        and all(value["cross_namespace_source_count"] == 0 for value in arms.values())
        else "FAIL",
        "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
    }


def _arm_metrics(rows: Sequence[Mapping[str, Any]], arm: str) -> dict[str, Any]:
    values = [value["arms"][arm]["retrieval_metrics"] for value in rows]
    complete = sum(value["all_required_evidence_group_recall"] is True for value in values)
    any_session = sum(value["any_gold_session_recall"] is True for value in values)
    return {
        "complete_evidence_set_count": complete,
        "complete_evidence_set_rate": complete / len(values) if values else 0.0,
        "mean_group_coverage": (
            sum(float(value["reader_visible_evidence_group_coverage"]) for value in values)
            / len(values)
            if values
            else 0.0
        ),
        "any_gold_session_recall_count": any_session,
        "any_gold_session_recall_rate": any_session / len(values) if values else 0.0,
        "mean_answer_session_coverage": (
            sum(float(value["reader_visible_answer_session_coverage"]) for value in values)
            / len(values)
            if values
            else 0.0
        ),
    }


def _comparison(rows: Sequence[Mapping[str, Any]], arm: str) -> dict[str, Any]:
    baseline_complete = {
        int(value["ordinal"])
        for value in rows
        if value["arms"]["A"]["retrieval_metrics"][
            "all_required_evidence_group_recall"
        ]
        is True
    }
    current_complete = {
        int(value["ordinal"])
        for value in rows
        if value["arms"][arm]["retrieval_metrics"][
            "all_required_evidence_group_recall"
        ]
        is True
    }
    recovered = current_complete - baseline_complete
    lost = baseline_complete - current_complete
    lost_any_session = {
        int(value["ordinal"])
        for value in rows
        if value["arms"]["A"]["retrieval_metrics"]["any_gold_session_recall"]
        is True
        and value["arms"][arm]["retrieval_metrics"]["any_gold_session_recall"]
        is False
    }
    by_ordinal = {int(value["ordinal"]): value for value in rows}
    baseline_metrics = _arm_metrics(rows, "A")
    current_metrics = _arm_metrics(rows, arm)
    return {
        "complete_case_gain": current_metrics["complete_evidence_set_count"]
        - baseline_metrics["complete_evidence_set_count"],
        "mean_group_coverage_gain": current_metrics["mean_group_coverage"]
        - baseline_metrics["mean_group_coverage"],
        "any_gold_session_recall_gain": current_metrics["any_gold_session_recall_rate"]
        - baseline_metrics["any_gold_session_recall_rate"],
        "recovered_case_hashes": sorted(
            str(by_ordinal[value]["case_id_sha256"]) for value in recovered
        ),
        "lost_case_hashes": sorted(
            str(by_ordinal[value]["case_id_sha256"]) for value in lost
        ),
        "lost_any_gold_session_case_hashes": sorted(
            str(by_ordinal[value]["case_id_sha256"]) for value in lost_any_session
        ),
        "recovered_shape_count": len(
            {str(by_ordinal[value]["capability_family"]) for value in recovered}
        ),
        "recovered_shapes": sorted(
            {str(by_ordinal[value]["capability_family"]) for value in recovered}
        ),
    }


async def _run(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    if args.output.exists():
        raise Product07R3ContextError("output path already exists")
    selected, identities = _load_inputs(
        args.selection,
        args.source_selection,
        args.dataset_manifest,
        "R3",
    )
    if len(selected) != 24:
        raise Product07R3ContextError("frozen R3 selection must contain exactly 24 cases")
    case_ids = [str(record["question_id"]) for _metadata, record in selected]
    labels = _load_labels(args.answer_turn_labels, case_ids)
    lock = load_product_lock(args.product_lock)
    verification = verify_product_lock(lock, PRODUCT)
    if not verification.valid:
        raise Product07R3ContextError(
            "Product pin failed: " + "; ".join(verification.errors)
        )
    v0_summary = json.loads((args.v0_run / "summary.json").read_text(encoding="utf-8"))
    if (
        v0_summary.get("p07_v0_b1_development_gate") is not True
        or v0_summary.get("all_required_evidence_group_recall_count") != 11
        or float(v0_summary.get("reader_visible_evidence_group_coverage", 0.0)) < 0.90
        or v0_summary.get("previously_complete_loss_count") != 0
        or v0_summary.get("p07_h1_gate") is not False
    ):
        raise Product07R3ContextError("V0 B1 development closure is absent or drifted")

    args.output.mkdir(mode=0o700, parents=True)
    scratch = Path(tempfile.mkdtemp(prefix="m7-r3-context-", dir="/tmp"))
    scratch.chmod(0o700)
    project = f"{args.run_id}-pg"
    compose: list[str] = []
    postgres_started = False
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    database: dict[str, Any] = {"canonical": -1, "evidence": {}, "projection": {}}
    run_lock = {
        "schema": "milai.product07.r3-context.run-lock.v1",
        "run_id": args.run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "stage": "S2_R3_CONTEXT_ONLY_H1",
        "tier": "R3",
        "case_count": 24,
        "arms": list(ARMS),
        "arm_definitions": {
            "A": "CURRENT_PRODUCT_RECALL",
            "B0": "QUERY_PRESERVING_SIMPLE_UNION",
            "B1": "B0_SAME_POOL_SOFT_EVIDENCESET_SELECTION",
        },
        "one_capture_namespace_per_case": True,
        "same_namespace_across_arms": True,
        "answer_or_judge_calls_authorized": False,
        "answer_calls": 0,
        "judge_calls": 0,
        "provider_calls": 0,
        "model_identity": MODEL,
        "product_lock_digest": lock.digest,
        "product_tree_sha256": lock.tree_sha256,
        "product_lock_sha256": _sha256_file(args.product_lock),
        "runner_sha256": _sha256_file(Path(__file__)),
        "selection_sha256": identities["selection_sha256"],
        "dataset_sha256": identities["dataset_sha256"],
        "dataset_manifest_sha256": identities["dataset_manifest_sha256"],
        "answer_turn_labels_sha256": _sha256_file(args.answer_turn_labels),
        "v0_development_run_id": v0_summary.get("run_id"),
        "v0_development_summary_sha256": _sha256_file(args.v0_run / "summary.json"),
        "v0_development_gate": True,
        "budget": {
            "unique_retrieval_candidates": 240,
            "hydrated_evidence_units": 160,
            "reader_visible_tokens_requested": 16_384,
            "reader_visible_tokens_effective": 16_384,
            "effective_budget_source": "RUNTIME_CONTEXT_BUDGET_ENVELOPE",
            "memory_deadline_ms": 10_000,
            "semantic_retries": 0,
            "votes": 0,
        },
        "treatment_excludes": [
            "case_id",
            "reference_answer",
            "gold_terms",
            "gold_sessions",
            "scorer_outcomes",
        ],
        "opened_development_only": True,
        "r3_context_consumed": True,
        "r3_answers_consumed": False,
        "formal_holdout_consumed": False,
        "postgres_project": project,
        "postgres_volume_preserved_after_run": True,
    }
    _write_json(args.output / "run-lock.json", run_lock)
    try:
        postgres_port = _free_port()
        base_env_path = scratch / "postgres.env"
        _command(
            [
                str(OPS_EXE),
                "init",
                "--env-file",
                str(base_env_path),
                "--blob-root",
                str(scratch / "base-blobs"),
                "--postgres-port",
                str(postgres_port),
                "--api-port",
                str(_free_port()),
            ],
            cwd=RUNTIME,
        )
        base_environment = _load_environment(base_env_path)
        compose = [
            "docker",
            "compose",
            "--project-name",
            project,
            "--env-file",
            str(base_env_path),
            "--file",
            str(RUNTIME / "compose.yaml"),
        ]
        _command([*compose, "up", "--detach", "postgres"], cwd=RUNTIME, timeout=120)
        postgres_started = True
        deadline = time.monotonic() + 90
        while True:
            migration = _command(
                [str(ALEMBIC_EXE), "-c", "alembic.ini", "upgrade", "head"],
                cwd=RUNTIME,
                env=_clean_environment(
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
                raise Product07R3ContextError("fresh PostgreSQL migration failed")
            await asyncio.sleep(1)

        cases = [
            _make_case(
                ordinal=ordinal,
                metadata=metadata,
                record=record,
                scratch=scratch,
                base_environment=base_environment,
            )
            for ordinal, (metadata, record) in enumerate(selected, start=1)
        ]
        semaphore = asyncio.Semaphore(args.case_concurrency)

        async def guarded(case: ContextCase) -> dict[str, Any]:
            async with semaphore:
                value = await _one_case(
                    case,
                    answer_label=labels[str(case.record["question_id"])],
                    capture_concurrency=args.capture_concurrency,
                )
                print(
                    json.dumps(
                        {
                            "ordinal": case.ordinal,
                            "case_id_sha256": value["case_id_sha256"],
                            "status": value["status"],
                            "coverage": {
                                arm: value["arms"][arm]["retrieval_metrics"][
                                    "reader_visible_evidence_group_coverage"
                                ]
                                for arm in ARMS
                            },
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                return value

        gathered = await asyncio.gather(
            *(guarded(case) for case in cases), return_exceptions=True
        )
        for case, value in zip(cases, gathered, strict=True):
            if isinstance(value, BaseException):
                failures.append(
                    {
                        "ordinal": case.ordinal,
                        "case_id_sha256": _sha256_text(
                            str(case.record["question_id"])
                        ),
                        "category": "INFRASTRUCTURE_OR_CONTRACT",
                        "message": str(value),
                    }
                )
            else:
                rows.append(value)
        rows.sort(key=lambda value: int(value["ordinal"]))
        database = _database_audit(f"{project}-postgres-1")
    finally:
        if postgres_started:
            _command([*compose, "down"], cwd=RUNTIME, timeout=90, check=False)
        shutil.rmtree(scratch)

    _write_jsonl(args.output / "cases.jsonl", rows)
    _write_jsonl(args.output / "failure-notes.jsonl", failures)
    arm_metrics = {arm: _arm_metrics(rows, arm) for arm in ARMS}
    comparisons = {arm: _comparison(rows, arm) for arm in ("B0", "B1")}
    same_pool_counts = {
        key: sum(value["same_pool"][key] is True for value in rows)
        for key in (
            "candidate_set_match",
            "acquired_order_match",
            "window_closure_match",
            "hydration_count_match",
            "effective_budget_match",
        )
    }
    observed_budgets = sorted(
        {
            int(value["arms"][arm]["trace"]["budget_envelope"]["available_memory_tokens"])
            for value in rows
            for arm in ARMS
            if isinstance(value["arms"][arm]["trace"].get("budget_envelope"), Mapping)
            and isinstance(
                value["arms"][arm]["trace"]["budget_envelope"].get(
                    "available_memory_tokens"
                ),
                int,
            )
        }
    )
    expected_tenants = 24
    database_valid = (
        database["canonical"] == 0
        and len(database["evidence"]) == expected_tenants
        and database["evidence"] == database["projection"]
    )
    b1 = comparisons["B1"]
    full_slice = (
        len(rows) == 24
        and not failures
        and all(value["status"] == "PASS" for value in rows)
    )
    safety_valid = (
        database_valid
        and sum(
            int(value["arms"][arm]["cross_namespace_source_count"])
            for value in rows
            for arm in ARMS
        )
        == 0
        and all(
            value["arms"][arm]["trace"]["canonical_mutation"] is False
            for value in rows
            for arm in ARMS
        )
        and all(
            int(value["arms"][arm]["trace"]["hidden_model_calls"] or 0) == 0
            for value in rows
            for arm in ARMS
        )
    )
    h1_gate = (
        full_slice
        and b1["complete_case_gain"] >= 4
        and b1["mean_group_coverage_gain"] >= 0.10
        and b1["recovered_shape_count"] >= 3
        and not b1["lost_any_gold_session_case_hashes"]
        and not b1["lost_case_hashes"]
        and all(value == 24 for value in same_pool_counts.values())
        and observed_budgets == [16_384]
        and safety_valid
    )
    failed_conditions = [
        name
        for name, passed in (
            ("FULL_R3_SLICE", full_slice),
            ("COMPLETE_CASE_GAIN_GE_4", b1["complete_case_gain"] >= 4),
            ("GROUP_COVERAGE_GAIN_GE_0_10", b1["mean_group_coverage_gain"] >= 0.10),
            ("RECOVERED_SHAPES_GE_3", b1["recovered_shape_count"] >= 3),
            ("ANY_GOLD_SESSION_NO_REGRESSION", not b1["lost_any_gold_session_case_hashes"]),
            ("PREVIOUSLY_COMPLETE_LOSS_ZERO", not b1["lost_case_hashes"]),
            ("B0_B1_SAME_POOL_24", all(value == 24 for value in same_pool_counts.values())),
            ("EFFECTIVE_BUDGET_16384", observed_budgets == [16_384]),
            ("SAFETY", safety_valid),
        )
        if not passed
    ]
    summary = {
        "schema": "milai.product07.r3-context.summary.v1",
        "run_id": args.run_id,
        "stage": "S2_R3_CONTEXT_ONLY_H1",
        "case_count": len(rows),
        "failure_count": len(failures),
        "full_r3_slice": full_slice,
        "arm_metrics": arm_metrics,
        "comparisons_to_A": comparisons,
        "same_pool_match_counts": same_pool_counts,
        "observed_effective_reader_token_budgets": observed_budgets,
        "database_namespace_count": len(database["evidence"]),
        "database_projection_consistent": database["evidence"] == database["projection"],
        "canonical_mutation_count": database["canonical"],
        "cross_namespace_source_count": sum(
            int(value["arms"][arm]["cross_namespace_source_count"])
            for value in rows
            for arm in ARMS
        ),
        "hidden_model_call_count": sum(
            int(value["arms"][arm]["trace"]["hidden_model_calls"] or 0)
            for value in rows
            for arm in ARMS
        ),
        "answer_calls": 0,
        "judge_calls": 0,
        "provider_calls": 0,
        "p07_v0_b1_development_gate": True,
        "p07_h1_gate": h1_gate,
        "p07_h1_failed_conditions": failed_conditions,
        "selected_retrieval_method": "B1" if h1_gate else None,
        "r3_context_consumed": True,
        "r3_answers_consumed": False,
        "formal_holdout_consumed": False,
        "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
    }
    _write_json(args.output / "summary.json", summary)
    terminal = {
        "schema": "milai.product07.r3-context.terminal.v1",
        "run_id": args.run_id,
        "terminal": "PASS_P07_H1_B1" if h1_gate else "FAIL_P07_H1_B1",
        "p07_h1_gate": h1_gate,
        "answer_or_judge_executed": False,
        "r3_context_consumed": True,
        "r3_answers_consumed": False,
        "formal_holdout_consumed": False,
        "summary_sha256": _sha256_file(args.output / "summary.json"),
    }
    _write_json(args.output / "terminal.json", terminal)
    if len([value for value in args.output.iterdir() if value.is_file()]) != 5:
        raise Product07R3ContextError("formal run did not retain exactly five files")
    return 0 if not failures else 2


def main() -> int:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.disable(logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--source-selection", type=Path, default=DEFAULT_SOURCE_SELECTION)
    parser.add_argument("--answer-turn-labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--dataset-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--product-lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--v0-run", type=Path, default=DEFAULT_V0_RUN)
    parser.add_argument("--case-concurrency", type=int, default=4, choices=range(1, 5))
    parser.add_argument("--capture-concurrency", type=int, default=4, choices=range(1, 5))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 8 <= len(args.run_id) <= 42 or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in args.run_id
    ):
        raise SystemExit("run-id must contain 8-42 lowercase alphanumeric/hyphen characters")
    for name in (
        "selection",
        "source_selection",
        "answer_turn_labels",
        "dataset_manifest",
        "product_lock",
        "v0_run",
        "output",
    ):
        setattr(args, name, getattr(args, name).resolve(strict=False))
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        raise SystemExit(
            f"Product-07 R3 Context-only failed: {type(exc).__name__}: {exc}"
        ) from exc


if __name__ == "__main__":
    raise SystemExit(main())
