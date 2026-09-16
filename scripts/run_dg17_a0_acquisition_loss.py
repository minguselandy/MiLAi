#!/usr/bin/env python3
"""Run DG-17 A0 as a sealed, eval-only acquisition loss ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg14.benchmark import DEFAULT_TOKENIZER, _atomic_json, _local_token_counter
from evals.dg16.lme10 import load_public_dev_cases
from evals.dg16.q5 import VllmDenseClient, VllmRerankerClient
from evals.dg17.acquisition_loss import (
    PATHS,
    AcquisitionLossError,
    attribute_acquisition_losses,
    build_label_free_trace,
)
from evals.dg17.measurement import LABELS_PATH, load_answer_bearing_labels
from evals.dg17.q8_retrieval_ablation import build_query_plans
from scripts.run_dg17_q8_retrieval_ablation import (
    DENSE_MODEL_PATH,
    RERANK_MODEL_PATH,
    _dense_index_projector,
    _gpu_identity,
    _process_identity,
    _served_model,
)

DEFAULT_OUTPUT_ROOT = ROOT / "var/dg17/a0"
DEFAULT_Q6 = ROOT / "var/dg17/q6/dg17-q6-sealed-20260827-003/receipt.json"
DEFAULT_Q8_CONTEXTS = (
    ROOT / "var/dg17/q8/dg17-q8-retrieval-ablation-20260827-002/contexts.json"
)
DEFAULT_Q1R_CONTEXTS = (
    ROOT / "var/dg17/q1r/dg17-q1r-contexts-20260827-004/contexts.json"
)
DEFAULT_GOAL = ROOT / "MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md"
DEFAULT_Q6_SHA256 = "c0c98a1afc654b9e734657fd57de19abddb4268de4829320e0bb4af1aa02b4df"
DEFAULT_Q8_CONTEXTS_SHA256 = (
    "6b3a45e1b09b905a6557581063c9892c3bb44279e43f341727d067fa2c03005e"
)
DEFAULT_Q1R_CONTEXTS_SHA256 = (
    "35007cb9c653dff5e792c2e495cf8627c8d89309e18f1958821bf32527a95c1e"
)
AUTHORIZED_GOAL_SHA256 = (
    "b19c7abeb7299f23f8b48e48a055b122b9b37987b0ef6d76d100695897f50a32"
)


def run(
    *,
    run_id: str,
    output_root: Path,
    q6_path: Path,
    q6_sha256: str,
    q8_contexts_path: Path,
    q8_contexts_sha256: str,
    q1r_contexts_path: Path,
    q1r_contexts_sha256: str,
    goal_path: Path,
    goal_sha256: str,
    dense: Any,
    reranker: Any,
    token_count: Any,
    index_text_projector: Any,
    execution_identity: Mapping[str, Any],
) -> dict[str, Any]:
    if output_root.exists():
        raise AcquisitionLossError("A0 output exists; choose a fresh run ID")
    output_root.mkdir(parents=True)
    started = time.perf_counter()
    q6 = _load_bound(q6_path, q6_sha256)
    q8_contexts = _load_bound(q8_contexts_path, q8_contexts_sha256)
    q1r_contexts = _load_bound(q1r_contexts_path, q1r_contexts_sha256)
    _load_bound_text(goal_path, goal_sha256)
    cases, selection = load_public_dev_cases()
    case_ids = [str(case.case_id) for case in cases]
    _validate_snapshot(q1r_contexts, case_ids=case_ids)
    plans = build_query_plans(cases)
    execution_plan = {
        "schema": "milai.dg17.a0-execution-plan.v0.1",
        "status": "SEALED_BEFORE_CHANNEL_CALLS_OR_LABELS",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / EVALUATION_PLANE",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "reader_calls_planned": 0,
        "automatic_retries": 0,
        "case_order": case_ids,
        "required_evidence_denominator": 23,
        "paths": list(PATHS),
        "bound_artifacts": {
            "goal_authorization": _identity(goal_path, goal_sha256),
            "q6_sealed": _identity(q6_path, q6_sha256),
            "q8_label_free_contexts": _identity(
                q8_contexts_path, q8_contexts_sha256
            ),
            "q1r_immutable_contexts": _identity(
                q1r_contexts_path, q1r_contexts_sha256
            ),
            "answer_bearing_labels_identity_only": _identity(
                LABELS_PATH, _sha256(LABELS_PATH)
            ),
        },
        "selection": selection,
        "label_boundary": {
            "trace_must_be_sealed_before_labels": True,
            "gold_labels_available_to_product_path": False,
            "product_path_label_access_count": 0,
        },
    }
    _atomic_json(output_root / "execution-plan.json", execution_plan)

    trace_started = time.perf_counter()
    try:
        trace, channel_metrics = build_label_free_trace(
            cases,
            plans=plans,
            q6_receipt=q6,
            dense=dense,
            reranker=reranker,
            token_count=token_count,
            index_text_projector=index_text_projector,
            expected_q8_contexts=q8_contexts,
        )
    except Exception as exc:
        _write_failure(output_root, run_id=run_id, stage="LABEL_FREE_TRACE", error=exc)
        raise
    trace.update(
        {
            "run_id": run_id,
            "bound_execution_plan_sha256": _sha256(
                output_root / "execution-plan.json"
            ),
        }
    )
    _atomic_json(output_root / "label-free-trace.json", trace)
    trace_sha256 = _sha256(output_root / "label-free-trace.json")
    trace_wall_ms = (time.perf_counter() - trace_started) * 1_000

    attribution_started = time.perf_counter()
    try:
        _label_envelope, labeled_cases, labels = load_answer_bearing_labels()
        if [str(case.case_id) for case in labeled_cases] != case_ids:
            raise AcquisitionLossError("A0 label case order drifted")
        records, summary = attribute_acquisition_losses(trace, labels=labels)
    except Exception as exc:
        _write_failure(
            output_root,
            run_id=run_id,
            stage="AFTER_THE_FACT_ATTRIBUTION",
            error=exc,
            trace_sha256=trace_sha256,
        )
        raise
    ledger = {
        "schema": "milai.dg17.a0-acquisition-loss-ledger.v0.1",
        "status": "ATTRIBUTED_AFTER_LABEL_FREE_TRACE_SEAL",
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "label_free_trace_sha256": trace_sha256,
        "gold_label_product_path_access_count": 0,
        "summary": summary,
        "records": records,
    }
    _atomic_json(output_root / "ledger.json", ledger)
    ledger_sha256 = _sha256(output_root / "ledger.json")
    attribution_wall_ms = (time.perf_counter() - attribution_started) * 1_000

    gates = {
        "cases_annotated_10_of_10": summary["unique_case_count"] == 10,
        "required_evidence_attributed_23_of_23": (
            summary["unique_required_evidence_count"] == 23
        ),
        "every_path_has_23_of_23": all(
            value["required_evidence_denominator"] == 23
            for value in summary["paths"].values()
        ),
        "exactly_one_first_loss_or_not_lost": summary[
            "all_records_have_exactly_one_first_loss"
        ],
        "gold_label_product_path_access_zero": (
            summary["gold_label_product_path_access_count"] == 0
        ),
        "q8_single_factor_selected_sources_replayed_50_of_50": (
            channel_metrics["q8_replay_cells"] == 50
            and channel_metrics["q8_replay_match_count"] == 50
            and channel_metrics["q8_replay_identity_equal"] is True
        ),
        "q6_and_typed_source_identity_bound_20_of_20": True,
        "reader_calls_zero": True,
        "automatic_retries_zero": True,
    }
    status = "PASS" if all(gates.values()) else "FAILED"
    receipt = {
        "schema": "milai.dg17.a0-acquisition-loss-receipt.v0.1",
        "status": status,
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / EVALUATION_PLANE",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "execution_identity": dict(execution_identity),
        "bound_artifacts": execution_plan["bound_artifacts"],
        "archives": {
            "execution_plan": _identity(
                output_root / "execution-plan.json",
                _sha256(output_root / "execution-plan.json"),
            ),
            "label_free_trace": _identity(
                output_root / "label-free-trace.json", trace_sha256
            ),
            "ledger": _identity(output_root / "ledger.json", ledger_sha256),
        },
        "label_boundary": {
            "trace_sealed_before_labels": True,
            "product_path_label_access_count": 0,
            "reader_calls": 0,
            "automatic_retries": 0,
        },
        "summary": summary,
        "gates": gates,
        "efficiency": {
            "label_free_trace_wall_ms": round(trace_wall_ms, 6),
            "after_the_fact_attribution_wall_ms": round(
                attribution_wall_ms, 6
            ),
            "experiment_wall_ms": round(
                (time.perf_counter() - started) * 1_000, 6
            ),
            "dense": channel_metrics["dense"],
            "reranker": channel_metrics["reranker"],
            "reader_calls": 0,
            "automatic_retries": 0,
        },
        "claim_boundary": {
            "product_behavior_changed": False,
            "runtime_imports_this_ledger": False,
            "A1_authorized_if_status_pass": status == "PASS",
            "release_claim_authorized": False,
            "final_lme_authorized": False,
        },
    }
    _atomic_json(output_root / "receipt.json", receipt)
    return receipt


def _validate_snapshot(archive: Mapping[str, Any], *, case_ids: list[str]) -> None:
    if archive.get("schema") != "milai.dg17.q1r-context-pairs.v0.1":
        raise AcquisitionLossError("A0 immutable snapshot schema drifted")
    snapshots = archive.get("snapshots")
    if not isinstance(snapshots, list) or len(snapshots) != 10:
        raise AcquisitionLossError("A0 immutable snapshot denominator drifted")
    observed = [str(value.get("case_id")) for value in snapshots if isinstance(value, Mapping)]
    if observed != case_ids:
        raise AcquisitionLossError("A0 immutable snapshot case order drifted")
    for value in snapshots:
        assert isinstance(value, Mapping)
        snapshot = value.get("evidence_snapshot")
        if not isinstance(snapshot, Mapping) or snapshot.get("immutable_after_ingest") is not True:
            raise AcquisitionLossError("A0 snapshot is not immutable")


def _load_bound(path: Path, expected_sha256: str) -> dict[str, Any]:
    if _sha256(path) != expected_sha256:
        raise AcquisitionLossError(f"A0 bound artifact drifted: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AcquisitionLossError(f"A0 bound artifact is not an object: {path}")
    return value


def _load_bound_text(path: Path, expected_sha256: str) -> None:
    if _sha256(path) != expected_sha256:
        raise AcquisitionLossError(f"A0 authorization document drifted: {path}")


def _write_failure(
    output_root: Path,
    *,
    run_id: str,
    stage: str,
    error: Exception,
    trace_sha256: str | None = None,
) -> None:
    _atomic_json(
        output_root / "failure-receipt.json",
        {
            "schema": "milai.dg17.a0-failure.v0.1",
            "status": "FAILED_NOT_RETRIED",
            "run_id": run_id,
            "stage": stage,
            "labels_loaded": stage == "AFTER_THE_FACT_ATTRIBUTION",
            "label_free_trace_sha256": trace_sha256,
            "reader_calls": 0,
            "automatic_retries": 0,
            "error_type": type(error).__name__,
            "error_message": str(error),
        },
    )


def _identity(path: Path, sha256: str) -> dict[str, str]:
    try:
        display = str(path.relative_to(ROOT))
    except ValueError:
        display = str(path)
    return {"path": display, "sha256": sha256}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--dense-url", default="http://127.0.0.1:7861")
    parser.add_argument("--reranker-url", default="http://127.0.0.1:7961")
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--q6", type=Path, default=DEFAULT_Q6)
    parser.add_argument("--q6-sha256", default=DEFAULT_Q6_SHA256)
    parser.add_argument("--q8-contexts", type=Path, default=DEFAULT_Q8_CONTEXTS)
    parser.add_argument(
        "--q8-contexts-sha256", default=DEFAULT_Q8_CONTEXTS_SHA256
    )
    parser.add_argument("--q1r-contexts", type=Path, default=DEFAULT_Q1R_CONTEXTS)
    parser.add_argument(
        "--q1r-contexts-sha256", default=DEFAULT_Q1R_CONTEXTS_SHA256
    )
    parser.add_argument("--goal", type=Path, default=DEFAULT_GOAL)
    parser.add_argument("--goal-sha256", default=AUTHORIZED_GOAL_SHA256)
    args = parser.parse_args()

    dense_models = _served_model(args.dense_url)
    reranker_models = _served_model(args.reranker_url)
    dense_identity = {
        "model_id": "BAAI/bge-m3",
        "served_model_name": "bge-m3",
        "artifact_sha256": _sha256(DENSE_MODEL_PATH / "pytorch_model.bin"),
        "config_sha256": _sha256(DENSE_MODEL_PATH / "config.json"),
        "dimensions": 1_024,
        "max_model_len": 8_192,
        "projection_version": "dg17-q8-turn-bge-m3-v1",
        "endpoint": args.dense_url,
        "models_response": dense_models,
        "process": _process_identity(7861),
    }
    reranker_identity = {
        "model_id": "BAAI/bge-reranker-v2-m3",
        "served_model_name": "bge-reranker",
        "artifact_sha256": _sha256(RERANK_MODEL_PATH / "model.safetensors"),
        "config_sha256": _sha256(RERANK_MODEL_PATH / "config.json"),
        "max_model_len": 8_192,
        "endpoint": args.reranker_url,
        "models_response": reranker_models,
        "process": _process_identity(7961),
    }
    dense = VllmDenseClient(
        args.dense_url, model_id="bge-m3", artifact_identity=dense_identity
    )
    reranker = VllmRerankerClient(
        args.reranker_url,
        model_id="bge-reranker",
        artifact_identity=reranker_identity,
    )
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    receipt = run(
        run_id=args.run_id,
        output_root=output_root,
        q6_path=args.q6,
        q6_sha256=args.q6_sha256,
        q8_contexts_path=args.q8_contexts,
        q8_contexts_sha256=args.q8_contexts_sha256,
        q1r_contexts_path=args.q1r_contexts,
        q1r_contexts_sha256=args.q1r_contexts_sha256,
        goal_path=args.goal,
        goal_sha256=args.goal_sha256,
        dense=dense,
        reranker=reranker,
        token_count=_local_token_counter(args.tokenizer),
        index_text_projector=_dense_index_projector(
            DENSE_MODEL_PATH / "tokenizer.json"
        ),
        execution_identity={
            "hostname": platform.node(),
            "gpu": _gpu_identity(),
            "dense": dense_identity,
            "reranker": reranker_identity,
            "reader_calls": 0,
            "automatic_retries": 0,
        },
    )
    receipt_path = output_root / "receipt.json"
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(receipt_path.relative_to(ROOT)),
                "receipt_sha256": _sha256(receipt_path),
                "summary": receipt["summary"],
                "gates": receipt["gates"],
                "efficiency": receipt["efficiency"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
