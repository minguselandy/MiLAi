#!/usr/bin/env python3
"""Replay frozen Product-06 source namespaces through Product-07 Context only.

This runner never asks a Provider for an answer and never scores an answer. It
starts the current Product Runtime and the trusted MCP broker against the
preserved PostgreSQL/Evidence namespace, then evaluates only Reader-visible
source-turn coverage using the independently frozen answer-turn labels.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import tempfile
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milai_lab.product_adapter.manifest import load_product_lock, verify_product_lock
from run_product05_openworker_lme import (
    API_EXE,
    BROKER_EXE,
    LAB,
    MODEL,
    PRODUCT,
    RUNTIME,
    ManagedProcesses,
    _broker_resolve,
    _clean_environment,
    _free_port,
    _load_environment,
    _load_inputs,
    _policy,
    _retrieval_metrics,
    _sha256_file,
    _sha256_text,
    _wait_http,
    _wait_socket,
)

DEFAULT_SOURCE_RUN = (
    LAB / "var/runs/mila-p06-r2-v0-r1-202609030857"
)
DEFAULT_SELECTION = LAB / "data/labels/product06-reader-selection.v0.1.json"
DEFAULT_SOURCE_SELECTION = LAB / "data/labels/product03-context24-selection.v0.1.json"
DEFAULT_LABELS = LAB / "data/labels/product02-longmemeval-answer-turns-qwen36-v4.json"
DEFAULT_MANIFEST = LAB / "data/manifests/longmemeval-s-cleaned-500.json"
DEFAULT_LOCK = LAB / "data/locks/product07-product-s1.lock.json"


class Product07ContextReplayError(RuntimeError):
    pass


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def _receipt_sources(snapshot: Mapping[str, Any]) -> list[dict[str, str]]:
    receipt = snapshot.get("context_receipt")
    mappings = receipt.get("receipt_mapping") if isinstance(receipt, Mapping) else None
    if not isinstance(mappings, list):
        raise Product07ContextReplayError("Context receipt mapping is absent")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for mapping in mappings:
        if not isinstance(mapping, Mapping):
            raise Product07ContextReplayError("Context receipt mapping is invalid")
        evidence_ids = mapping.get("evidence_ids")
        source_refs = mapping.get("source_turn_refs")
        if not isinstance(evidence_ids, list) or not isinstance(source_refs, list):
            continue
        if len(evidence_ids) != len(source_refs):
            raise Product07ContextReplayError("Context receipt lineage is not one-to-one")
        for evidence_id, source_ref in zip(evidence_ids, source_refs, strict=True):
            if not isinstance(evidence_id, str) or not isinstance(source_ref, str):
                raise Product07ContextReplayError("Context receipt source identity is invalid")
            if evidence_id in seen:
                continue
            rows.append({"evidence_id": evidence_id, "source_ref": source_ref})
            seen.add(evidence_id)
    return rows


def _trace_summary(
    memory_context: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> dict[str, Any]:
    compile_trace = memory_context.get("compile_trace")
    if not isinstance(compile_trace, Mapping):
        raise Product07ContextReplayError("Memory Context compile trace is absent")
    if compile_trace.get("canonical_mutation") is not False:
        raise Product07ContextReplayError("Context path did not prove mutation absence")
    acquired = compile_trace.get("acquired_candidate_trace")
    admitted = compile_trace.get("admitted_evidence_trace")
    visible = compile_trace.get("reader_visible_trace")
    if not all(isinstance(value, Mapping) for value in (acquired, admitted, visible)):
        raise Product07ContextReplayError("Evidence lifecycle trace is incomplete")
    search_trace = snapshot.get("search_trace")
    search = search_trace if isinstance(search_trace, Mapping) else {}
    dispositions = search.get("acquisition_probe_dispositions")
    disposition_rows = (
        [dict(value) for value in dispositions if isinstance(value, Mapping)]
        if isinstance(dispositions, list)
        else []
    )
    dense = [value for value in disposition_rows if value.get("channel") == "EVIDENCE_DENSE"]
    acquired_candidates = acquired.get("candidates")
    acquired_rows = (
        [value for value in acquired_candidates if isinstance(value, Mapping)]
        if isinstance(acquired_candidates, list)
        else []
    )
    admitted_refs = admitted.get("selected_source_turn_refs")
    admitted_source_refs = (
        [value for value in admitted_refs if isinstance(value, str)]
        if isinstance(admitted_refs, list)
        else []
    )
    rendered_units = visible.get("rendered_units")
    rendered_rows = (
        [value for value in rendered_units if isinstance(value, Mapping)]
        if isinstance(rendered_units, list)
        else []
    )
    visible_source_refs = {
        value
        for unit in rendered_rows
        for value in unit.get("source_turn_refs", [])
        if isinstance(value, str)
    }
    candidate_windows = compile_trace.get("candidate_window_trace")
    candidate_window_rows = (
        [value for value in candidate_windows if isinstance(value, Mapping)]
        if isinstance(candidate_windows, list)
        else []
    )
    return {
        "compiler_version": compile_trace.get("compiler_version"),
        "acquired_candidate_count": acquired.get("candidate_count"),
        "acquired_trace_sha256": acquired.get("trace_sha256"),
        "acquired_ranked_source_turn_sha256s": [
            _sha256_text(str(value["source_turn_ref"]))
            for value in acquired_rows
            if isinstance(value.get("source_turn_ref"), str)
        ],
        "admitted_evidence_count": len(admitted.get("selected_evidence_ids", [])),
        "admitted_trace_sha256": admitted.get("trace_sha256"),
        "admitted_source_turn_sha256s": sorted(
            _sha256_text(value) for value in admitted_source_refs
        ),
        "reader_visible_evidence_count": len(rendered_rows),
        "reader_visible_trace_sha256": visible.get("trace_sha256"),
        "reader_visible_source_turn_sha256s": sorted(
            _sha256_text(value) for value in visible_source_refs
        ),
        "selected_window_count": memory_context.get("selected_windows"),
        "available_window_count": memory_context.get("available_windows"),
        "estimated_context_tokens": memory_context.get("estimated_tokens"),
        "context_truncated": memory_context.get("context_truncated"),
        "locality_hydrated_count": len(compile_trace.get("expansion_trace", [])),
        "omitted_unit_reasons": compile_trace.get("omitted_unit_reasons"),
        "plan_omitted_units": compile_trace.get("plan_omitted_units"),
        "conditional_unit_order": compile_trace.get("conditional_unit_order"),
        "selected_conditional_unit_ids": compile_trace.get(
            "selected_conditional_unit_ids"
        ),
        "candidate_window_trace": [
            {
                key: value.get(key)
                for key in (
                    "window_id",
                    "source_rank",
                    "query_overlap",
                    "answer_signal",
                    "requirement_priority",
                    "estimated_tokens",
                )
            }
            | {
                "source_turn_sha256s": [
                    _sha256_text(source_ref)
                    for source_ref in value.get("source_turn_refs", [])
                    if isinstance(source_ref, str)
                ],
                "session_sha256": (
                    _sha256_text(str(value["session_id"]))
                    if isinstance(value.get("session_id"), str)
                    else None
                ),
            }
            for value in candidate_window_rows
        ],
        "protected_closure_tokens": compile_trace.get("protected_closure_tokens"),
        "session_diversity_enabled": compile_trace.get(
            "session_diversity_objective_enabled",
            compile_trace.get("multi_session_requirement"),
        ),
        "query_preserving_union_enabled": compile_trace.get(
            "query_preserving_union_enabled"
        ),
        "evidence_set_selection_enabled": compile_trace.get(
            "evidence_set_selection_enabled"
        ),
        "recall_workspace_trace": compile_trace.get("recall_workspace_trace"),
        "budget_envelope": compile_trace.get("budget_envelope"),
        "dense_dispositions": dense,
        "canonical_mutation": False,
        "hidden_model_calls": compile_trace.get("hidden_model_calls"),
    }


async def _one_case(
    *,
    ordinal: int,
    metadata: dict[str, Any],
    record: dict[str, Any],
    answer_label: Mapping[str, Any],
    source_run: Path,
    scratch: Path,
    treatment: bool,
    evidence_set_selection: bool = False,
    query_override: str | None = None,
) -> dict[str, Any]:
    label = f"c{ordinal:02d}"
    source_root = source_run / "private" / label
    if not source_root.is_dir():
        raise Product07ContextReplayError(f"preserved source case is absent: {label}")
    environment = _load_environment(source_root / "runtime.env")
    environment.update(
        {
            "MILAI_BIND_PORT": str(_free_port()),
            "MILAI_BASE_URL": "",
            "MILAI_BLOB_ROOT": str(source_root / "blobs"),
            "MILAI_RETRIEVAL_QUERY_PRESERVING_UNION_ENABLED": (
                "true" if treatment or evidence_set_selection else "false"
            ),
            "MILAI_RETRIEVAL_EVIDENCE_SET_SELECTION_ENABLED": (
                "true" if evidence_set_selection else "false"
            ),
        }
    )
    environment["MILAI_BASE_URL"] = f"http://127.0.0.1:{environment['MILAI_BIND_PORT']}"
    case_root = scratch / label
    case_root.mkdir(mode=0o700)
    socket_root = case_root / "reader-lite"
    socket_root.mkdir(mode=0o700)
    socket_path = socket_root / "reader-lite.sock"
    policy_path = case_root / "reader.policy.json"
    token_path = case_root / "reader.token"
    _write_json(policy_path, _policy(socket_path, environment["MILAI_BASE_URL"]))
    token_path.write_text(environment["MILAI_AGENT_READER_TOKEN"] + "\n", encoding="utf-8")
    token_path.chmod(0o600)
    processes = ManagedProcesses()
    started = time.perf_counter()
    try:
        api = processes.start(
            [str(API_EXE)],
            case_root / "api.log",
            cwd=RUNTIME,
            env=_clean_environment(environment),
        )
        await asyncio.to_thread(
            _wait_http,
            f"{environment['MILAI_BASE_URL']}/health/ready",
            api,
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
            case_root / "broker.log",
        )
        await asyncio.to_thread(_wait_socket, socket_path, broker)
        question = query_override or str(record["question"])
        prompt = (
            f"Reference date: {record['question_date']}\n"
            f"{question}\n"
            "Answer concisely using only the governed memory supplied for this operation."
        )
        snapshot = await asyncio.to_thread(_broker_resolve, socket_path, prompt)
    finally:
        processes.stop_all()

    memory_context = snapshot.get("memory_context")
    if not isinstance(memory_context, Mapping) or not isinstance(
        memory_context.get("text"), str
    ):
        raise Product07ContextReplayError("Reader-visible Context is absent")
    selected = memory_context.get("selected_evidence_ids")
    if not isinstance(selected, list) or any(not isinstance(value, str) for value in selected):
        raise Product07ContextReplayError("selected Evidence identities are invalid")
    receipts = _receipt_sources(snapshot)
    metrics = _retrieval_metrics(record, receipts, selected, answer_label)
    expected_prefix = f"lme://{_sha256_text(str(record['question_id']))[:12]}/"
    selected_refs = {
        row["source_ref"] for row in receipts if row["evidence_id"] in set(selected)
    }
    cross_namespace = sum(not value.startswith(expected_prefix) for value in selected_refs)
    trace = _trace_summary(memory_context, snapshot)
    if trace.get("hidden_model_calls") != 0:
        raise Product07ContextReplayError("Context-only replay made a hidden model call")
    return {
        "ordinal": ordinal,
        # Kept only in process for evaluator joins.  Product never receives it,
        # and it is stripped before persisted artifacts are written.
        "_case_id": str(record["question_id"]),
        "case_id_sha256": _sha256_text(str(record["question_id"])),
        "query_type": metadata.get("query_type"),
        "capability_family": metadata.get("capability_family"),
        "context_sha256": _sha256_text(str(memory_context["text"])),
        "query_sha256": _sha256_text(question),
        "selected_evidence_count": len(selected),
        "selected_source_turn_count": len(selected_refs),
        "selected_source_identity_digest": _canonical_sha256(sorted(selected_refs)),
        "retrieval_metrics": metrics,
        "trace": trace,
        "cross_namespace_source_count": cross_namespace,
        "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
        "status": "PASS" if cross_namespace == 0 else "FAIL",
        "_context_text": str(memory_context["text"]),
        "_selected_source_refs": sorted(selected_refs),
        "_memory_context_payload": dict(memory_context),
        "_context_receipt_payload": (
            dict(snapshot["context_receipt"])
            if isinstance(snapshot.get("context_receipt"), Mapping)
            else {}
        ),
    }


def _baseline_by_id(source_run: Path) -> dict[str, dict[str, Any]]:
    path = source_run / "private/cases.private.jsonl"
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {str(value["case_id"]): value for value in values}


async def _run(args: argparse.Namespace) -> int:
    if args.output.exists():
        raise Product07ContextReplayError("output path already exists")
    args.output.mkdir(mode=0o700, parents=True)
    selected, identities = _load_inputs(
        args.selection,
        args.source_selection,
        args.dataset_manifest,
        args.tier,
    )
    if args.tier != "V0":
        raise Product07ContextReplayError("preserved context replay is only available for V0")
    requested_ordinals = {
        int(value) for value in args.ordinals.split(",") if value.strip()
    } if args.ordinals else set()
    selected_rows = [
        (ordinal, metadata, record)
        for ordinal, (metadata, record) in enumerate(selected, start=1)
        if not requested_ordinals or ordinal in requested_ordinals
    ]
    if requested_ordinals != {value[0] for value in selected_rows} and requested_ordinals:
        raise Product07ContextReplayError("requested ordinal is outside the frozen V0 tier")
    lock = load_product_lock(args.product_lock)
    verification = verify_product_lock(lock, PRODUCT)
    if not verification.valid:
        raise Product07ContextReplayError("Product pin failed: " + "; ".join(verification.errors))
    label_payload = json.loads(args.answer_turn_labels.read_text(encoding="utf-8"))
    labels = {
        str(value["case_id"]): value
        for value in label_payload.get("cases", [])
        if isinstance(value, Mapping) and isinstance(value.get("case_id"), str)
    }
    source_run_payload = json.loads((args.source_run / "run.json").read_text(encoding="utf-8"))
    if (
        source_run_payload.get("selection_sha256") != identities["selection_sha256"]
        or source_run_payload.get("dataset_sha256") != identities["dataset_sha256"]
    ):
        raise Product07ContextReplayError("preserved source run identity drifted")
    baseline = _baseline_by_id(args.source_run)
    missing_labels = [
        str(record["question_id"])
        for _ordinal, _metadata, record in selected_rows
        if str(record["question_id"]) not in labels or str(record["question_id"]) not in baseline
    ]
    if missing_labels:
        raise Product07ContextReplayError("frozen labels or baseline rows are incomplete")

    run_lock = {
        "schema": "milai.product07.context-replay.run-lock.v1",
        "run_id": args.run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "stage": "S2_SAME_POOL_SELECTION" if args.evidence_set_selection else "S1_CONTEXT_ONLY",
        "treatment": (
            "SAME_POOL_SOFT_EVIDENCESET_SELECTION"
            if args.evidence_set_selection
            else "QUERY_PRESERVING_SIMPLE_UNION"
            if args.treatment
            else "P06_BASELINE"
        ),
        "answer_or_judge_calls_authorized": False,
        "answer_or_judge_calls": 0,
        "product_lock_digest": lock.digest,
        "product_tree_sha256": lock.tree_sha256,
        "product_lock_sha256": _sha256_file(args.product_lock),
        "source_run_id": source_run_payload.get("run_id"),
        "source_run_sha256": _sha256_file(args.source_run / "run.json"),
        "source_summary_sha256": _sha256_file(args.source_run / "summary.json"),
        "selection_sha256": identities["selection_sha256"],
        "answer_turn_labels_sha256": _sha256_file(args.answer_turn_labels),
        "dataset_sha256": identities["dataset_sha256"],
        "dataset_manifest_sha256": identities["dataset_manifest_sha256"],
        "tier": args.tier,
        "ordinals": [value[0] for value in selected_rows],
        "model_identity": MODEL,
        "provider_calls": 0,
        "formal_holdout_consumed": False,
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
    }
    _write_json(args.output / "run-lock.json", run_lock)

    scratch = Path(tempfile.mkdtemp(prefix="m7-context-", dir="/tmp"))
    scratch.chmod(0o700)
    semaphore = asyncio.Semaphore(args.case_concurrency)

    async def guarded(
        ordinal: int, metadata: dict[str, Any], record: dict[str, Any]
    ) -> dict[str, Any]:
        async with semaphore:
            result = await _one_case(
                ordinal=ordinal,
                metadata=metadata,
                record=record,
                answer_label=labels[str(record["question_id"])],
                source_run=args.source_run,
                scratch=scratch,
                treatment=args.treatment,
                evidence_set_selection=args.evidence_set_selection,
            )
            print(
                json.dumps(
                    {
                        "ordinal": ordinal,
                        "case_id_sha256": result["case_id_sha256"],
                        "coverage": result["retrieval_metrics"][
                            "reader_visible_evidence_group_coverage"
                        ],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            return result

    started = time.perf_counter()
    failures: list[dict[str, Any]] = []
    try:
        gathered = await asyncio.gather(
            *(guarded(*value) for value in selected_rows),
            return_exceptions=True,
        )
    finally:
        shutil.rmtree(scratch)
    rows: list[dict[str, Any]] = []
    for source, value in zip(selected_rows, gathered, strict=True):
        if isinstance(value, BaseException):
            failure = {
                "ordinal": source[0],
                "case_id_sha256": _sha256_text(str(source[2]["question_id"])),
                "category": "INFRASTRUCTURE_OR_CONTRACT",
                "message": str(value),
            }
            failures.append(failure)
        else:
            rows.append(value)
    rows.sort(key=lambda value: int(value["ordinal"]))
    public_rows = [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in rows
    ]
    _write_jsonl(args.output / "cases.jsonl", public_rows)
    _write_jsonl(args.output / "failure-notes.jsonl", failures)

    baseline_complete = {
        case_id
        for case_id, value in baseline.items()
        if value["retrieval_metrics"]["all_required_evidence_group_recall"] is True
    }
    baseline_incomplete = {
        case_id
        for case_id, value in baseline.items()
        if value["retrieval_metrics"]["all_required_evidence_group_recall"] is False
    }
    current_by_id = {str(value["_case_id"]): value for value in rows}
    current_complete = {
        case_id
        for case_id, value in current_by_id.items()
        if value["retrieval_metrics"]["all_required_evidence_group_recall"] is True
    }
    recovered = baseline_incomplete & current_complete
    lost = baseline_complete - current_complete if len(rows) == len(selected) else set()
    recovered_shapes = {
        str(current_by_id[case_id]["capability_family"])
        for case_id in recovered
        if case_id in current_by_id
    }
    all_required_count = len(current_complete)
    group_coverage = (
        sum(
            float(value["retrieval_metrics"]["reader_visible_evidence_group_coverage"])
            for value in rows
        )
        / len(rows)
        if rows
        else 0.0
    )
    full_slice = len(rows) == len(selected) == 12 and not failures
    legacy_v0_h1_gate = (
        full_slice
        and all_required_count >= 10
        and group_coverage >= 0.90
        and len(recovered) >= 3
        and len(recovered_shapes) >= 3
        and not lost
        and all(value["cross_namespace_source_count"] == 0 for value in rows)
        and all(value["trace"]["canonical_mutation"] is False for value in rows)
    )
    comparison_rows = (
        {
            int(value["ordinal"]): value
            for value in (
                json.loads(line)
                for line in (args.comparison_run / "cases.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            )
        }
        if args.evidence_set_selection
        else {}
    )
    same_pool_matches = sum(
        set(value["trace"]["acquired_ranked_source_turn_sha256s"])
        == set(comparison_rows.get(int(value["ordinal"]), {}).get("trace", {}).get(
            "acquired_ranked_source_turn_sha256s", []
        ))
        for value in rows
    )
    same_pool_acquired_order_matches = sum(
        value["trace"]["acquired_ranked_source_turn_sha256s"]
        == comparison_rows.get(int(value["ordinal"]), {}).get("trace", {}).get(
            "acquired_ranked_source_turn_sha256s", []
        )
        for value in rows
    )
    same_pool_window_closure_matches = sum(
        value["trace"]["candidate_window_trace"]
        == comparison_rows.get(int(value["ordinal"]), {}).get("trace", {}).get(
            "candidate_window_trace", []
        )
        for value in rows
    )
    comparison_complete = {
        ordinal
        for ordinal, value in comparison_rows.items()
        if value["retrieval_metrics"]["all_required_evidence_group_recall"] is True
    }
    current_complete_ordinals = {
        int(value["ordinal"])
        for value in rows
        if value["retrieval_metrics"]["all_required_evidence_group_recall"] is True
    }
    current_by_ordinal = {int(value["ordinal"]): value for value in rows}
    same_pool_recovered = current_complete_ordinals - comparison_complete
    same_pool_lost = comparison_complete - current_complete_ordinals
    comparison_group_coverage = (
        sum(
            float(value["retrieval_metrics"]["reader_visible_evidence_group_coverage"])
            for value in comparison_rows.values()
        )
        / len(comparison_rows)
        if comparison_rows
        else 0.0
    )
    effective_budgets = {
        int(value["trace"]["budget_envelope"]["available_memory_tokens"])
        for value in rows
        if isinstance(value["trace"].get("budget_envelope"), Mapping)
        and isinstance(
            value["trace"]["budget_envelope"].get("available_memory_tokens"), int
        )
    }
    development_gate = (
        full_slice
        and all_required_count >= 11
        and group_coverage >= 0.90
        and not lost
        and same_pool_matches == len(rows)
        and same_pool_acquired_order_matches == len(rows)
        and same_pool_window_closure_matches == len(rows)
        and effective_budgets == {16_384}
        and all(value["cross_namespace_source_count"] == 0 for value in rows)
        and all(value["trace"]["canonical_mutation"] is False for value in rows)
    )
    summary = {
        "schema": "milai.product07.context-replay.summary.v1",
        "run_id": args.run_id,
        "stage": (
            "S2_SAME_POOL_SELECTION"
            if args.evidence_set_selection
            else "S1_CONTEXT_ONLY"
        ),
        "case_count": len(rows),
        "failure_count": len(failures),
        "full_v0_slice": full_slice,
        "all_required_evidence_group_recall_count": all_required_count,
        "all_required_evidence_group_recall_rate": (
            all_required_count / len(rows) if rows else 0.0
        ),
        "reader_visible_evidence_group_coverage": group_coverage,
        "recovered_incomplete_context_count": len(recovered),
        "recovered_case_hashes": sorted(_sha256_text(value) for value in recovered),
        "recovered_shape_count": len(recovered_shapes),
        "recovered_shapes": sorted(recovered_shapes),
        "previously_complete_loss_count": len(lost),
        "lost_case_hashes": sorted(_sha256_text(value) for value in lost),
        "cross_namespace_source_count": sum(
            int(value["cross_namespace_source_count"]) for value in rows
        ),
        "canonical_mutation_count": sum(
            int(value["trace"]["canonical_mutation"] is not False) for value in rows
        ),
        "hidden_model_call_count": sum(
            int(value["trace"]["hidden_model_calls"] or 0) for value in rows
        ),
        "answer_calls": 0,
        "judge_calls": 0,
        "p07_h1_gate": (
            False if args.evidence_set_selection else legacy_v0_h1_gate
        ),
        "p07_h1_gate_reason": (
            "R3_CONTEXT_ONLY_NOT_CONSUMED"
            if args.evidence_set_selection
            else "LEGACY_V0_GATE"
        ),
        "p07_v0_b1_development_gate": (
            development_gate if args.evidence_set_selection else None
        ),
        "same_pool_candidate_set_match_count": (
            same_pool_matches if args.evidence_set_selection else None
        ),
        "same_pool_acquired_order_match_count": (
            same_pool_acquired_order_matches if args.evidence_set_selection else None
        ),
        "same_pool_window_closure_match_count": (
            same_pool_window_closure_matches if args.evidence_set_selection else None
        ),
        "same_pool_complete_case_gain": (
            len(current_complete_ordinals) - len(comparison_complete)
            if args.evidence_set_selection
            else None
        ),
        "same_pool_group_coverage_gain": (
            group_coverage - comparison_group_coverage
            if args.evidence_set_selection
            else None
        ),
        "same_pool_recovered_case_hashes": (
            sorted(
                current_by_ordinal[ordinal]["case_id_sha256"]
                for ordinal in same_pool_recovered
            )
            if args.evidence_set_selection
            else None
        ),
        "same_pool_lost_case_hashes": (
            sorted(
                comparison_rows[ordinal]["case_id_sha256"]
                for ordinal in same_pool_lost
            )
            if args.evidence_set_selection
            else None
        ),
        "observed_effective_reader_token_budgets": sorted(effective_budgets),
        "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
        "formal_holdout_consumed": False,
    }
    _write_json(args.output / "summary.json", summary)
    terminal = {
        "schema": "milai.product07.context-replay.terminal.v1",
        "run_id": args.run_id,
        "terminal": (
            "PASS_P07_V0_B1_DEVELOPMENT_GATE"
            if args.evidence_set_selection and development_gate
            else "FAIL_P07_V0_B1_DEVELOPMENT_GATE"
            if args.evidence_set_selection
            else "PASS_P07_H1_SIMPLE_UNION"
            if legacy_v0_h1_gate
            else "CONTEXT_REPLAY_PARTIAL"
            if not full_slice
            else "FAIL_P07_H1_SIMPLE_UNION"
        ),
        "p07_h1_gate": (
            False if args.evidence_set_selection else legacy_v0_h1_gate
        ),
        "p07_v0_b1_development_gate": (
            development_gate if args.evidence_set_selection else None
        ),
        "answer_or_judge_executed": False,
        "formal_holdout_consumed": False,
        "summary_sha256": _sha256_file(args.output / "summary.json"),
    }
    _write_json(args.output / "terminal.json", terminal)
    return 0 if not failures else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, default=DEFAULT_SOURCE_RUN)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--source-selection", type=Path, default=DEFAULT_SOURCE_SELECTION)
    parser.add_argument("--answer-turn-labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--dataset-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--product-lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument(
        "--comparison-run",
        type=Path,
        default=Path("var/product07/s1-v0-simple-r2"),
    )
    parser.add_argument("--tier", default="V0")
    parser.add_argument("--ordinals", default="")
    parser.add_argument("--case-concurrency", type=int, default=4, choices=range(1, 5))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--treatment", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--evidence-set-selection", action="store_true")
    args = parser.parse_args()
    for name in (
        "source_run",
        "selection",
        "source_selection",
        "answer_turn_labels",
        "dataset_manifest",
        "product_lock",
        "comparison_run",
        "output",
    ):
        setattr(args, name, getattr(args, name).resolve(strict=False))
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
