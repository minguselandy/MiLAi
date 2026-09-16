#!/usr/bin/env python3
"""Run Product-08 A/C/X/Y Context repair on the opened 24-case R3 slice.

A is a normal Product black-box continuity arm. C, X, and Y are PRODUCT_TESTKIT
views compiled from one process-local acquisition snapshot. No answer Provider,
Judge, or formal holdout is invoked by this runner.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from milai_lab.product_adapter.manifest import load_product_lock, verify_product_lock
from run_product05_openworker_lme import (
    ALEMBIC_EXE,
    OPS_EXE,
    PRODUCT,
    RUNTIME,
    SCOPE_PROJECT,
    _clean_environment,
    _command,
    _database_audit,
    _free_port,
    _history_events,
    _load_environment,
    _load_inputs,
    _retrieval_metrics,
    _sha256_file,
    _sha256_text,
)
from run_product07_context_replay import _write_json, _write_jsonl
from run_product07_r3_context import (
    DEFAULT_LABELS,
    DEFAULT_MANIFEST,
    DEFAULT_SELECTION,
    DEFAULT_SOURCE_SELECTION,
    ContextCase,
    _arm_metrics,
    _arm_result,
    _capture_case,
    _comparison,
    _load_labels,
    _make_case,
    _resolve_arm,
)

TESTKIT_EXE = RUNTIME / ".venv/bin/milai-context-testkit"
DEFAULT_LOCK = Path(__file__).resolve().parents[1] / "data/locks/product08-product.lock.json"
ARMS = ("A", "C", "X", "Y")
TESTKIT_ARMS = ("C", "X", "Y")


class Product08ContextRepairError(RuntimeError):
    pass


def _failure_messages(error: BaseException) -> list[str]:
    """Preserve nested TaskGroup causes in the lightweight failure artifact."""
    if isinstance(error, BaseExceptionGroup):
        return [
            message
            for nested in error.exceptions
            for message in _failure_messages(nested)
        ]
    return [f"{type(error).__name__}: {error}"]


def _prompt(case: ContextCase) -> str:
    return (
        f"Reference date: {case.record['question_date']}\n"
        f"{case.record['question']}\n"
        "Answer concisely using only the governed memory supplied for this operation."
    )


def _validate_testkit_report(report: Mapping[str, Any]) -> None:
    if report.get("schema_version") != "milai-context-testkit-report-v0.1":
        raise Product08ContextRepairError("Product testkit report schema drifted")
    snapshot = report.get("snapshot")
    invariants = report.get("invariants")
    arms = report.get("arms")
    if not isinstance(snapshot, Mapping) or not isinstance(invariants, Mapping):
        raise Product08ContextRepairError("Product testkit snapshot is absent")
    if not isinstance(arms, Mapping) or set(arms) != set(TESTKIT_ARMS):
        raise Product08ContextRepairError("Product testkit arm set drifted")
    if snapshot.get("raw_evidence_text_emitted") is not False:
        raise Product08ContextRepairError("Product testkit emitted Raw Evidence text")
    required_invariants = {
        "snapshot_build_count": 1,
        "c_x_before_boundary_equal": True,
        "c_x_decision_snapshot_equal": True,
        "replay_external_calls": 0,
        "workspace_enabled": False,
        "context_mutation_performed": False,
        "canonical_mutation": False,
    }
    if any(invariants.get(key) != value for key, value in required_invariants.items()):
        raise Product08ContextRepairError("Product testkit replay invariant failed")
    snapshot_digest = snapshot.get("snapshot_digest")
    if not isinstance(snapshot_digest, str) or len(snapshot_digest) != 64:
        raise Product08ContextRepairError("Product testkit snapshot digest is invalid")
    for arm in TESTKIT_ARMS:
        value = arms.get(arm)
        if not isinstance(value, Mapping) or value.get("snapshot_digest") != snapshot_digest:
            raise Product08ContextRepairError(f"{arm} did not use the frozen snapshot")
        if any(
            value.get(counter) != 0
            for counter in (
                "fresh_repository_calls",
                "fresh_embedding_calls",
                "fresh_vector_calls",
            )
        ):
            raise Product08ContextRepairError(f"{arm} made a fresh replay call")
        if value.get("canonical_mutation") is not False:
            raise Product08ContextRepairError(f"{arm} did not prove mutation absence")


def _run_testkit(case: ContextCase) -> dict[str, Any]:
    environment = dict(case.environment)
    environment.pop("MILAI_PROGRESSIVE_CONTEXT_EVIDENCE_V0_1", None)
    environment.update(
        {
            "MILAI_RETRIEVAL_QUERY_PRESERVING_UNION_ENABLED": "false",
            "MILAI_RETRIEVAL_ADDITIVE_UNION_V0_2_ENABLED": "true",
            "MILAI_RETRIEVAL_EVIDENCE_SET_SELECTION_ENABLED": "false",
            "MILAI_RETRIEVAL_TYPE_DIRECTED_ACQUISITION_ENABLED": "false",
            "MILAI_READER_INFORMATIONAL_SOFT_ADMISSION_V0_2_ENABLED": "true",
            "MILAI_RETRIEVAL_EVIDENCE_DENSE_ENABLED": "true",
        }
    )
    payload = {
        "schema_version": "milai-context-testkit-request-v0.1",
        "memory_request": {
            "query": _prompt(case),
            "invocation_mode": "EXPLICIT_READ",
            "requested_scope": {"project_ids": [SCOPE_PROJECT]},
            "required_authority": "INFORMATIONAL",
            "required_freshness": "CURRENT",
            "consistency_mode": "CANONICAL_REQUIRED",
            "budget": {
                "max_results": 50,
                "max_candidates": 120,
                "max_context_tokens": 16_384,
                "max_latency_ms": 5_000,
            },
        },
    }
    completed = subprocess.run(  # noqa: S603 - pinned local Product executable
        [str(TESTKIT_EXE)],
        cwd=RUNTIME,
        env=_clean_environment(environment),
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        check=False,
        timeout=180,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode(errors="replace")[-3_000:]
        raise Product08ContextRepairError(f"Product testkit failed: {message}")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise Product08ContextRepairError("Product testkit returned invalid JSON") from exc
    if not isinstance(report, Mapping):
        raise Product08ContextRepairError("Product testkit report is not an object")
    result = dict(report)
    _validate_testkit_report(result)
    return result


def _testkit_arm_result(
    *,
    case: ContextCase,
    arm: str,
    report: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    answer_label: Mapping[str, Any],
) -> dict[str, Any]:
    raw_arms = report.get("arms")
    if not isinstance(raw_arms, Mapping) or not isinstance(raw_arms.get(arm), Mapping):
        raise Product08ContextRepairError(f"{arm} testkit result is absent")
    value = dict(raw_arms[arm])
    selected = value.get("reader_visible_evidence_ids")
    selected_refs = value.get("reader_visible_source_turn_refs")
    captured_ids = {str(item["evidence_id"]) for item in receipts}
    captured_refs = {str(item["source_ref"]) for item in receipts}
    if (
        not isinstance(selected, list)
        or any(not isinstance(item, str) for item in selected)
        or not set(selected).issubset(captured_ids)
        or not isinstance(selected_refs, list)
        or any(not isinstance(item, str) for item in selected_refs)
        or not set(selected_refs).issubset(captured_refs)
    ):
        raise Product08ContextRepairError(f"{arm} selected identity is invalid")
    expected_prefix = f"lme://{_sha256_text(str(case.record['question_id']))[:12]}/"
    boundary = value.get("boundary")
    before = value.get("before_boundary")
    if not isinstance(boundary, Mapping) or not isinstance(before, Mapping):
        raise Product08ContextRepairError(f"{arm} boundary trace is absent")
    return {
        "arm_kind": "PRODUCT_TESTKIT",
        "context_sha256": value.get("context_digest"),
        "selected_evidence_count": len(selected),
        "selected_source_turn_count": len(selected_refs),
        "retrieval_metrics": _retrieval_metrics(
            case.record,
            receipts,
            selected,
            answer_label,
        ),
        "context_receipt_status": "NOT_APPLICABLE_PRODUCT_TESTKIT",
        "trace": value,
        "acquired_candidate_count": before.get("candidate_count"),
        "reader_boundary_before_count": len(boundary.get("before_boundary_ids", [])),
        "reader_boundary_after_count": len(boundary.get("after_boundary_ids", [])),
        "cross_namespace_source_count": sum(
            not item.startswith(expected_prefix) for item in selected_refs
        ),
    }


async def _one_case(
    case: ContextCase,
    *,
    answer_label: Mapping[str, Any],
    capture_concurrency: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    receipts = await _capture_case(case, capture_concurrency)
    baseline_snapshot = await _resolve_arm(case, "A")
    baseline = _arm_result(
        case=case,
        arm="A",
        snapshot=baseline_snapshot,
        receipts=receipts,
        answer_label=answer_label,
    )
    baseline["arm_kind"] = "PRODUCT_BLACK_BOX"
    report = await asyncio.to_thread(_run_testkit, case)
    arms = {"A": baseline}
    for arm in TESTKIT_ARMS:
        arms[arm] = _testkit_arm_result(
            case=case,
            arm=arm,
            report=report,
            receipts=receipts,
            answer_label=answer_label,
        )
    c_trace = arms["C"]["trace"]
    x_trace = arms["X"]["trace"]
    y_trace = arms["Y"]["trace"]
    c_visible = set(c_trace["reader_visible_evidence_ids"])
    x_visible = set(x_trace["reader_visible_evidence_ids"])
    invariants = report["invariants"]
    causal = {
        "c_x_before_boundary_match": (
            c_trace["before_boundary"]["trace_sha256"]
            == x_trace["before_boundary"]["trace_sha256"]
        ),
        "c_x_decision_snapshot_match": (
            c_trace["decision_snapshot_digest"]
            == x_trace["decision_snapshot_digest"]
        ),
        "c_reader_visible_subset_x": c_visible.issubset(x_visible),
        "x_nonempty_collapse": (
            int(x_trace["before_boundary"]["candidate_count"]) > 0
            and not x_trace["reader_visible_evidence_ids"]
        ),
        "y_nonempty_collapse": (
            int(y_trace["before_boundary"]["candidate_count"]) > 0
            and not y_trace["reader_visible_evidence_ids"]
        ),
        "dense_execution_valid": invariants.get("dense_execution_valid") is True,
        "replay_external_calls": invariants.get("replay_external_calls"),
    }
    status = "PASS" if (
        causal["c_x_before_boundary_match"]
        and causal["c_x_decision_snapshot_match"]
        and causal["c_reader_visible_subset_x"]
        and not causal["x_nonempty_collapse"]
        and not causal["y_nonempty_collapse"]
        and causal["dense_execution_valid"]
        and causal["replay_external_calls"] == 0
        and all(value["cross_namespace_source_count"] == 0 for value in arms.values())
    ) else "FAIL"
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
        "snapshot": report["snapshot"],
        "arms": arms,
        "causal_invariants": causal,
        "status": status,
        "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
    }


def _gate_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = {arm: _arm_metrics(rows, arm) for arm in ARMS}
    comparisons = {arm: _comparison(rows, arm) for arm in ("X", "Y")}
    c_x_before = sum(
        value["causal_invariants"]["c_x_before_boundary_match"] is True
        for value in rows
    )
    c_x_decision = sum(
        value["causal_invariants"]["c_x_decision_snapshot_match"] is True
        for value in rows
    )
    c_subset_x = sum(
        value["causal_invariants"]["c_reader_visible_subset_x"] is True
        for value in rows
    )
    x_collapses = sum(
        value["causal_invariants"]["x_nonempty_collapse"] is True for value in rows
    )
    y_collapses = sum(
        value["causal_invariants"]["y_nonempty_collapse"] is True for value in rows
    )
    dense_valid = sum(
        value["causal_invariants"]["dense_execution_valid"] is True
        for value in rows
    )
    y = comparisons["Y"]
    full_slice = len(rows) == 24 and all(value["status"] == "PASS" for value in rows)
    safety = (
        all(
            value["arms"][arm]["cross_namespace_source_count"] == 0
            for value in rows
            for arm in ARMS
        )
        and all(
            value["arms"][arm]["trace"].get("canonical_mutation") is False
            for value in rows
            for arm in TESTKIT_ARMS
        )
    )
    gate = (
        full_slice
        and c_x_before == 24
        and c_x_decision == 24
        and c_subset_x == 24
        and x_collapses == 0
        and y_collapses == 0
        and dense_valid == 24
        and y["complete_case_gain"] >= 4
        and y["mean_group_coverage_gain"] >= 0.10
        and y["recovered_shape_count"] >= 3
        and not y["lost_case_hashes"]
        and not y["lost_any_gold_session_case_hashes"]
        and safety
    )
    return {
        "arm_metrics": metrics,
        "comparisons_to_A": comparisons,
        "c_x_before_boundary_match_count": c_x_before,
        "c_x_decision_snapshot_match_count": c_x_decision,
        "c_reader_visible_subset_x_count": c_subset_x,
        "x_nonempty_collapse_count": x_collapses,
        "y_nonempty_collapse_count": y_collapses,
        "dense_execution_valid_count": dense_valid,
        "safety_valid": safety,
        "p08_context_gate": gate,
    }


async def _run(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    if args.output.exists():
        raise Product08ContextRepairError("output path already exists")
    if not TESTKIT_EXE.is_file():
        raise Product08ContextRepairError("published Product Context testkit is absent")
    if not args.embedding_model_path.is_dir():
        raise Product08ContextRepairError("frozen embedding model path is absent")
    selected, identities = _load_inputs(
        args.selection,
        args.source_selection,
        args.dataset_manifest,
        "R3",
    )
    if len(selected) != 24:
        raise Product08ContextRepairError("opened R3 selection must contain 24 cases")
    case_ids = [str(record["question_id"]) for _metadata, record in selected]
    labels = _load_labels(args.answer_turn_labels, case_ids)
    lock = load_product_lock(args.product_lock)
    interface_paths = {
        pin.interface_id: pin.path for pin in lock.public_interfaces
    }
    if interface_paths.get("context-testkit-v0.1") != "runtime/src/milai/testkit":
        raise Product08ContextRepairError(
            "Product pin does not publish context-testkit-v0.1"
        )
    verification = verify_product_lock(lock, PRODUCT)
    if not verification.valid:
        raise Product08ContextRepairError(
            "Product pin failed: " + "; ".join(verification.errors)
        )

    args.output.mkdir(mode=0o700, parents=True)
    scratch = Path(tempfile.mkdtemp(prefix="m8-context-repair-", dir="/tmp"))
    scratch.chmod(0o700)
    project = f"{args.run_id}-pg"
    compose: list[str] = []
    postgres_started = False
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    database: dict[str, Any] = {"canonical": -1, "evidence": {}, "projection": {}}
    run_lock = {
        "schema": "milai.product08.context-repair.run-lock.v1",
        "run_id": args.run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "stage": "P08_OPENED_R3_CONTEXT_ONLY",
        "tier": "OPENED_DEVELOPMENT_R3",
        "case_count": 24,
        "arms": list(ARMS),
        "arm_kinds": {
            "A": "PRODUCT_BLACK_BOX",
            "C": "PRODUCT_TESTKIT",
            "X": "PRODUCT_TESTKIT",
            "Y": "PRODUCT_TESTKIT",
        },
        "arm_definitions": {
            "A": "CURRENT_DIRECT_CONTINUITY_REFERENCE",
            "C": "FROZEN_GLOBAL_FTS_LEGACY_STRICT_ADMISSION",
            "X": "C_SAME_POOL_INFORMATIONAL_SOFT_ADMISSION_V02",
            "Y": "FROZEN_ADDITIVE_FTS_DENSE_SOFT_ADMISSION_V02",
        },
        "one_snapshot_build_per_case": True,
        "workspace_enabled": False,
        "dense_explicitly_enabled": True,
        "answer_calls": 0,
        "judge_calls": 0,
        "provider_calls": 0,
        "product_lock_digest": lock.digest,
        "product_tree_sha256": lock.tree_sha256,
        "product_lock_sha256": _sha256_file(args.product_lock),
        "runner_sha256": _sha256_file(Path(__file__)),
        "selection_sha256": identities["selection_sha256"],
        "dataset_sha256": identities["dataset_sha256"],
        "dataset_manifest_sha256": identities["dataset_manifest_sha256"],
        "answer_turn_labels_sha256": _sha256_file(args.answer_turn_labels),
        "embedding": {
            "provider": args.embedding_provider,
            "model_id": args.embedding_model_id,
            "source_dimensions": args.embedding_source_dimensions,
            "projection_dimensions": 128,
        },
        "treatment_excludes": [
            "case_id",
            "reference_answer",
            "gold_terms",
            "gold_sessions",
            "scorer_outcomes",
        ],
        "opened_development_only": True,
        "formal_holdout_consumed": False,
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
        base_environment.update(
            {
                "MILAI_EMBEDDING_PROVIDER": args.embedding_provider,
                "MILAI_EMBEDDING_MODEL_PATH": str(args.embedding_model_path),
                "MILAI_EMBEDDING_MODEL_ID": args.embedding_model_id,
                "MILAI_EMBEDDING_SOURCE_DIMENSIONS": str(
                    args.embedding_source_dimensions
                ),
                "MILAI_EMBEDDING_PROJECTION_DIMENSIONS": "128",
            }
        )
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
                raise Product08ContextRepairError("fresh PostgreSQL migration failed")
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
            *(guarded(case) for case in cases),
            return_exceptions=True,
        )
        for case, value in zip(cases, gathered, strict=True):
            if isinstance(value, BaseException):
                messages = _failure_messages(value)
                failures.append(
                    {
                        "ordinal": case.ordinal,
                        "case_id_sha256": _sha256_text(
                            str(case.record["question_id"])
                        ),
                        "category": "INFRASTRUCTURE_OR_CONTRACT",
                        "message": "; ".join(messages),
                        "causes": messages,
                    }
                )
            else:
                rows.append(value)
        rows.sort(key=lambda item: int(item["ordinal"]))
        database = _database_audit(f"{project}-postgres-1")
    finally:
        if postgres_started:
            _command([*compose, "down"], cwd=RUNTIME, timeout=90, check=False)
        shutil.rmtree(scratch)

    _write_jsonl(args.output / "cases.jsonl", rows)
    _write_jsonl(args.output / "failure-notes.jsonl", failures)
    gates = _gate_summary(rows)
    database_valid = (
        database["canonical"] == 0
        and len(database["evidence"]) == 24
        and database["evidence"] == database["projection"]
    )
    context_gate = gates["p08_context_gate"] is True and not failures and database_valid
    summary = {
        "schema": "milai.product08.context-repair.summary.v1",
        "run_id": args.run_id,
        "stage": "P08_OPENED_R3_CONTEXT_ONLY",
        "case_count": len(rows),
        "failure_count": len(failures),
        **gates,
        "database_projection_consistent": database["evidence"] == database["projection"],
        "canonical_mutation_count": database["canonical"],
        "answer_calls": 0,
        "judge_calls": 0,
        "provider_calls": 0,
        "p08_context_gate": context_gate,
        "selected_candidate": "Y" if context_gate else None,
        "default_switched": False,
        "opened_development_only": True,
        "formal_holdout_consumed": False,
        "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
    }
    _write_json(args.output / "summary.json", summary)
    _write_json(
        args.output / "terminal.json",
        {
            "schema": "milai.product08.context-repair.terminal.v1",
            "run_id": args.run_id,
            "terminal": (
                "PASS_P08_CONTEXT_CANDIDATE_DEFAULT_OFF"
                if context_gate
                else "FAIL_P08_CONTEXT_CANDIDATE_REMAINS_OFF"
            ),
            "p08_context_gate": context_gate,
            "default_switched": False,
            "answer_or_judge_executed": False,
            "formal_holdout_consumed": False,
            "summary_sha256": _sha256_file(args.output / "summary.json"),
        },
    )
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
    parser.add_argument("--embedding-model-path", type=Path, required=True)
    parser.add_argument(
        "--embedding-provider",
        choices=("onnx_sentence_transformer", "sentence_transformers"),
        default="onnx_sentence_transformer",
    )
    parser.add_argument("--embedding-model-id", required=True)
    parser.add_argument("--embedding-source-dimensions", type=int, required=True)
    parser.add_argument("--case-concurrency", type=int, default=2, choices=range(1, 5))
    parser.add_argument("--capture-concurrency", type=int, default=4, choices=range(1, 5))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 8 <= len(args.run_id) <= 42 or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
        for character in args.run_id
    ):
        raise SystemExit("run-id must contain 8-42 lowercase alphanumeric/hyphen characters")
    if args.embedding_source_dimensions < 128:
        raise SystemExit("embedding-source-dimensions must be at least 128")
    for name in (
        "selection",
        "source_selection",
        "answer_turn_labels",
        "dataset_manifest",
        "product_lock",
        "embedding_model_path",
        "output",
    ):
        setattr(args, name, getattr(args, name).resolve(strict=False))
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        raise SystemExit(
            f"Product-08 Context repair failed: {type(exc).__name__}: {exc}"
        ) from exc


if __name__ == "__main__":
    raise SystemExit(main())
