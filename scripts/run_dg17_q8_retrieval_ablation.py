#!/usr/bin/env python3
"""Run DG-17 Q8 as a sealed 10-case fixed-control retrieval ablation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg14.benchmark import DEFAULT_TOKENIZER, _atomic_json, _local_token_counter
from evals.dg14.provider import (
    MatchedVllmProvider,
    full_provider_contract,
    full_provider_contract_sha256,
)
from evals.dg16.lme10 import load_public_dev_cases, load_public_dev_labels
from evals.dg16.q5 import VllmDenseClient, VllmRerankerClient
from evals.dg17.measurement import load_answer_bearing_labels
from evals.dg17.q8_retrieval_ablation import (
    CANDIDATE_CAP,
    METHODS,
    RETRIEVAL_METHODS,
    RRF_K,
    TOKEN_BUDGET,
    TYPED_REFERENCE,
    DenseRetriever,
    IndexTextProjector,
    Q8Provider,
    Q8RetrievalError,
    Reranker,
    TokenCounter,
    build_q8_contexts,
    build_query_plans,
    canonical_sha256,
    provider_record,
    retrieval_query,
    score_q8_generations,
)
from evals.paper.provider import MODEL_ID, prompt_contract_sha256

DEFAULT_OUTPUT_ROOT = ROOT / "var/dg17/q8"
DEFAULT_Q0 = (
    ROOT / "var/dg17/q0/dg17-q0-multiseed-20260827-001/receipt.json"
)
DEFAULT_Q6 = ROOT / "var/dg17/q6/dg17-q6-sealed-20260827-003/receipt.json"
DEFAULT_Q1R_CONTEXTS = (
    ROOT / "var/dg17/q1r/dg17-q1r-contexts-20260827-004/contexts.json"
)
DENSE_MODEL_PATH = Path("/data/models/embed")
RERANK_MODEL_PATH = Path("/data/models/bge-reranker-v2-m3")
DENSE_INDEX_TOKEN_CAP = 7_680


def run(
    *,
    run_id: str,
    output_root: Path,
    q0_receipt: Path,
    q0_sha256: str,
    q6_receipt: Path,
    q6_sha256: str,
    q1r_context_archive: Path,
    q1r_context_sha256: str,
    dense: DenseRetriever,
    reranker: Reranker,
    provider: Q8Provider,
    token_count: TokenCounter,
    index_text_projector: IndexTextProjector,
    execution_identity: Mapping[str, Any],
) -> dict[str, Any]:
    if output_root.exists():
        raise Q8RetrievalError("Q8 output exists; choose a fresh run ID")
    output_root.mkdir(parents=True)
    started = time.perf_counter()
    q0 = _load_bound(q0_receipt, q0_sha256)
    q6 = _load_bound(q6_receipt, q6_sha256)
    q1r_contexts = _load_bound(q1r_context_archive, q1r_context_sha256)
    condition = _validate_condition(q0, q6)
    cases, selection = load_public_dev_cases()
    case_ids = [str(case.case_id) for case in cases]
    plans = build_query_plans(cases)
    schedule = [
        {
            "ordinal": ordinal,
            "case_id": case_id,
            "method": method,
            "token_budget": TOKEN_BUDGET,
        }
        for ordinal, (case_id, method) in enumerate(
            (case_id, method) for case_id in case_ids for method in METHODS
        )
    ]
    execution_plan = {
        "schema": "milai.dg17.q8-execution-plan.v0.1",
        "status": "SEALED_BEFORE_RETRIEVAL_OR_READER_CALLS",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / EVALUATION_PLANE",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "automatic_retries": 0,
        "planned_reader_calls": len(schedule),
        "fixed_controls": {
            "case_order": case_ids,
            "methods": list(METHODS),
            "single_factor_methods": list(RETRIEVAL_METHODS),
            "typed_reference": TYPED_REFERENCE,
            "primitive_evidence_unit": "TURN",
            "index_text_projection": "BGE_M3_TOKEN_PREFIX_7680_V1",
            "index_text_token_cap": DENSE_INDEX_TOKEN_CAP,
            "candidate_cap": CANDIDATE_CAP,
            "context_token_budget": TOKEN_BUDGET,
            "rrf_k": RRF_K,
            "reader_model_id": MODEL_ID,
            "prompt_contract_sha256": prompt_contract_sha256(),
            "generation_contract_sha256": full_provider_contract_sha256(),
            "memory_query_ir": {
                case_id: {
                    "query_plan": plans[case_id].model_dump(mode="json"),
                    "query_plan_digest": canonical_sha256(
                        plans[case_id].model_dump(mode="json")
                    ),
                    "retrieval_query": retrieval_query(
                        plans[case_id], str(cases[index].question)
                    ),
                }
                for index, case_id in enumerate(case_ids)
            },
        },
        "condition": condition,
        "selection": selection,
        "bound_artifacts": {
            "q0_multiseed": _identity(q0_receipt, q0_sha256),
            "q6_sealed": _identity(q6_receipt, q6_sha256),
            "q1r_context_archive": _identity(
                q1r_context_archive, q1r_context_sha256
            ),
        },
        "schedule": schedule,
    }
    _atomic_json(output_root / "execution-plan.json", execution_plan)

    try:
        contexts, retrieval_build = build_q8_contexts(
            cases,
            plans=plans,
            typed_context_archive=q1r_contexts,
            dense=dense,
            reranker=reranker,
            token_count=token_count,
            index_text_projector=index_text_projector,
        )
    except Exception as exc:
        _write_failure(
            output_root,
            run_id=run_id,
            stage="LABEL_FREE_CONTEXT_BUILD",
            completed_reader_calls=0,
            failed_call=None,
            error=exc,
        )
        raise
    context_archive = {
        "schema": "milai.dg17.q8-label-free-contexts.v0.1",
        "status": "SUCCEEDED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / EVALUATION_PLANE",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "label_fields_available_to_retrieval_path": False,
        "historical_answer_reuse": False,
        "automatic_retries": 0,
        "record_count": len(contexts),
        "retrieval_build": retrieval_build,
        "records": contexts,
    }
    _atomic_json(output_root / "contexts.json", context_archive)
    context_sha256 = _sha256(output_root / "contexts.json")

    context_index = {
        (str(row["case_id"]), str(row["method"])): row for row in contexts
    }
    case_index = {str(case.case_id): case for case in cases}
    generations: list[dict[str, Any]] = []
    _write_progress(
        output_root,
        run_id=run_id,
        planned_calls=len(schedule),
        generations=generations,
    )
    provider_started = time.perf_counter()
    for cell in schedule:
        case_id = str(cell["case_id"])
        method = str(cell["method"])
        ordinal = cell["ordinal"]
        if isinstance(ordinal, bool) or not isinstance(ordinal, int):
            raise Q8RetrievalError("Q8 schedule ordinal drifted")
        context = context_index[(case_id, method)]
        case = case_index[case_id]
        try:
            result = provider.answer(
                run_id=run_id,
                case_id=case_id,
                method_id=f"DG17-Q8-{method}",
                question=str(case.question),
                question_as_of=str(case.question_at),
                memory_context=str(context["context"]),
                token_budget=TOKEN_BUDGET,
            )
        except Exception as exc:
            failed_call = {
                "ordinal": ordinal,
                "case_id": case_id,
                "method": method,
                "token_budget": TOKEN_BUDGET,
            }
            _write_progress(
                output_root,
                run_id=run_id,
                planned_calls=len(schedule),
                generations=generations,
                failed_call=failed_call,
            )
            _write_failure(
                output_root,
                run_id=run_id,
                stage="READER_PROVIDER",
                completed_reader_calls=len(generations),
                failed_call=failed_call,
                error=exc,
            )
            raise Q8RetrievalError("Q8 Reader call failed without retry") from exc
        generations.append(
            {
                "call_ordinal": ordinal,
                "case_id": case_id,
                "method": method,
                "token_budget": TOKEN_BUDGET,
                "answer": result.answer,
                "context": result.context,
                "planned_context_sha256": context["context_sha256"],
                "planned_context_tokens": context["context_tokens"],
                "generation_source": "FRESH_PROVIDER_CALL",
                "historical_answer_reuse": False,
                "automatic_retries": 0,
                "provider": provider_record(result),
            }
        )
        _write_progress(
            output_root,
            run_id=run_id,
            planned_calls=len(schedule),
            generations=generations,
        )
    provider_wall_ms = (time.perf_counter() - provider_started) * 1_000
    generation_archive = {
        "schema": "milai.dg17.q8-generations.v0.1",
        "status": "SUCCEEDED",
        "classification": "UNSCORED_FRESH_READER_GENERATIONS",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "historical_answer_reuse": False,
        "automatic_retries": 0,
        "planned_call_count": len(schedule),
        "completed_call_count": len(generations),
        "context_archive_sha256": context_sha256,
        "records": generations,
    }
    _atomic_json(output_root / "generations.json", generation_archive)
    generation_sha256 = _sha256(output_root / "generations.json")
    _write_progress(
        output_root,
        run_id=run_id,
        planned_calls=len(schedule),
        generations=generations,
        generation_archive_sha256=generation_sha256,
    )

    scoring_started = time.perf_counter()
    _label_envelope, labeled_cases, answer_bearing_labels = (
        load_answer_bearing_labels()
    )
    if tuple(str(case.case_id) for case in labeled_cases) != tuple(case_ids):
        raise Q8RetrievalError("Q8 answer-bearing label case order drifted")
    scoring_labels, scoring_identity = load_public_dev_labels(tuple(case_ids))
    scored, summaries, decision = score_q8_generations(
        generations,
        contexts=contexts,
        cases=cases,
        answer_bearing_labels=answer_bearing_labels,
        scoring_labels=scoring_labels,
    )
    scoring_wall_ms = (time.perf_counter() - scoring_started) * 1_000
    receipt = {
        "schema": "milai.dg17.q8-strong-retrieval-ablation.v0.1",
        "status": "CHARACTERIZED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / EVALUATION_PLANE",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "formal_source_id_overlap": [],
        "configuration": execution_plan["fixed_controls"],
        "condition": condition,
        "selection": selection,
        "bound_artifacts": execution_plan["bound_artifacts"],
        "execution_identity": dict(execution_identity),
        "archives": {
            "execution_plan": _identity(
                output_root / "execution-plan.json",
                _sha256(output_root / "execution-plan.json"),
            ),
            "contexts": _identity(output_root / "contexts.json", context_sha256),
            "generations": _identity(
                output_root / "generations.json", generation_sha256
            ),
        },
        "label_boundary": {
            "contexts_and_generations_sealed_before_labels": True,
            "label_fields_available_to_retrieval_path": False,
            "scoring_label_source": scoring_identity,
            "product_path_label_access_count": 0,
        },
        "summaries": summaries,
        "decision": decision,
        "records": scored,
        "efficiency": {
            "retrieval_context_build_wall_ms": retrieval_build["wall_ms"],
            "provider_window_wall_ms": round(provider_wall_ms, 6),
            "scoring_wall_ms": round(scoring_wall_ms, 6),
            "experiment_wall_ms": round((time.perf_counter() - started) * 1_000, 6),
            "reader_calls": len(generations),
            "dense": retrieval_build["dense"],
            "reranker": retrieval_build["reranker"],
            "automatic_retries": 0,
        },
        "claim_boundary": {
            "production_retrieval_modified": False,
            "production_default_authorized": False,
            "completeness_proof_from_dense_or_reranker": False,
            "release_claim_authorized": False,
        },
    }
    _atomic_json(output_root / "receipt.json", receipt)
    return receipt


def _validate_condition(q0: Mapping[str, Any], q6: Mapping[str, Any]) -> dict[str, Any]:
    if (
        q0.get("schema") != "milai.dg17.q0-multiseed-oracle.v0.1"
        or q0.get("status") != "Q0_MULTI_SEED_ORACLE_CHARACTERIZED"
    ):
        raise Q8RetrievalError("Q8 Q0 oracle binding is not characterized")
    aggregate = q0.get("aggregate")
    per_arm = aggregate.get("per_arm") if isinstance(aggregate, Mapping) else None
    if not isinstance(per_arm, Mapping):
        raise Q8RetrievalError("Q8 Q0 oracle arm summary is missing")
    a = _nested_number(per_arm, "A_GOLD_EVIDENCE_GOLD_IR", "normalized_f1_mean")
    b = _nested_number(per_arm, "B_ACTUAL_EVIDENCE_GOLD_IR", "normalized_f1_mean")
    c = _nested_number(
        per_arm, "C_GOLD_EVIDENCE_PREDICTED_IR", "normalized_f1_mean"
    )
    d = _nested_number(
        per_arm, "D_ACTUAL_EVIDENCE_PREDICTED_IR", "normalized_f1_mean"
    )
    arms = q6.get("arms")
    current = arms.get("DG17_DETERMINISTIC_ONLY") if isinstance(arms, Mapping) else None
    current_2048 = current.get("2048") if isinstance(current, Mapping) else None
    if not isinstance(current_2048, Mapping):
        raise Q8RetrievalError("Q8 Q6 current 2048 summary is missing")
    coverage = _number(current_2048, "required_evidence_set_coverage")
    condition_satisfied = a > b and c > d and coverage < 0.8
    if not condition_satisfied:
        raise Q8RetrievalError("Q8 candidate-recall limiting condition is not satisfied")
    return {
        "status": "SATISFIED",
        "q0_gold_vs_actual_f1_delta_gold_ir": round(a - b, 9),
        "q0_gold_vs_actual_f1_delta_predicted_ir": round(c - d, 9),
        "q6_current_required_evidence_set_coverage": round(coverage, 9),
        "threshold_changed": False,
    }


def _write_progress(
    output_root: Path,
    *,
    run_id: str,
    planned_calls: int,
    generations: list[dict[str, Any]],
    failed_call: Mapping[str, Any] | None = None,
    generation_archive_sha256: str | None = None,
) -> None:
    status = "IN_PROGRESS_NOT_SCOREABLE"
    if failed_call is not None:
        status = "FAILED_NOT_SCOREABLE"
    elif generation_archive_sha256 is not None:
        status = "SUCCEEDED_GENERATION_ARCHIVE_SEALED"
    _atomic_json(
        output_root / "progress.json",
        {
            "schema": "milai.dg17.q8-provider-progress.v0.1",
            "status": status,
            "classification": "UNSCORED_PRIMARY_PROVIDER_PROGRESS",
            "run_id": run_id,
            "labels_loaded": False,
            "historical_answer_reuse": False,
            "automatic_retries": 0,
            "planned_call_count": planned_calls,
            "completed_call_count": len(generations),
            "failed_call": dict(failed_call) if failed_call is not None else None,
            "generation_archive_sha256": generation_archive_sha256,
            "records": generations,
        },
    )


def _write_failure(
    output_root: Path,
    *,
    run_id: str,
    stage: str,
    completed_reader_calls: int,
    failed_call: Mapping[str, Any] | None,
    error: Exception,
) -> None:
    _atomic_json(
        output_root / "failure-receipt.json",
        {
            "schema": "milai.dg17.q8-failure.v0.1",
            "status": "FAILED_NOT_SCOREABLE",
            "run_id": run_id,
            "stage": stage,
            "labels_loaded": False,
            "automatic_retries": 0,
            "completed_reader_calls": completed_reader_calls,
            "failed_call": dict(failed_call) if failed_call is not None else None,
            "error_type": type(error).__name__,
            "error_message": str(error),
        },
    )


def _load_bound(path: Path, expected_sha256: str) -> dict[str, Any]:
    if _sha256(path) != expected_sha256:
        raise Q8RetrievalError(f"Q8 bound artifact drifted: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Q8RetrievalError(f"Q8 bound artifact is invalid: {path}") from exc
    if not isinstance(value, dict):
        raise Q8RetrievalError(f"Q8 bound artifact must be an object: {path}")
    return value


def _nested_number(value: Mapping[str, Any], outer: str, inner: str) -> float:
    raw = value.get(outer)
    if not isinstance(raw, Mapping):
        raise Q8RetrievalError(f"Q8 metric group is missing: {outer}")
    return _number(raw, inner)


def _number(value: Mapping[str, Any], key: str) -> float:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise Q8RetrievalError(f"Q8 numeric field is missing: {key}")
    return float(raw)


def _identity(path: Path, sha256: str) -> dict[str, str]:
    try:
        relative = path.relative_to(ROOT)
        display = str(relative)
    except ValueError:
        display = str(path)
    return {"path": display, "sha256": sha256}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _process_identity(port: int) -> dict[str, Any]:
    marker = str(port)
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            arguments = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode()
        except (OSError, UnicodeDecodeError):
            continue
        if marker in arguments and "vllm" in arguments:
            return {"pid": int(entry.name), "command": arguments.strip()}
    return {"pid": None, "command": "UNAVAILABLE"}


def _gpu_identity() -> dict[str, Any]:
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,uuid,memory.used,memory.total,driver_version",
            "--format=csv,noheader",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", "UNSET"),
        "devices": completed.stdout.strip().splitlines(),
    }


def _served_model(base_url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/models", method="GET"
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise Q8RetrievalError("Q8 model identity response exceeded 4 MiB")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("data"), list):
        raise Q8RetrievalError("Q8 model identity response is malformed")
    return parsed


def _dense_index_projector(path: Path) -> IndexTextProjector:
    tokenizer = Tokenizer.from_file(str(path))

    def project(value: str) -> str:
        encoded = tokenizer.encode(value, add_special_tokens=False)
        if len(encoded.ids) <= DENSE_INDEX_TOKEN_CAP:
            return value
        return str(tokenizer.decode(encoded.ids[:DENSE_INDEX_TOKEN_CAP])).strip()

    return project


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--reader-url", default="http://127.0.0.1:7860")
    parser.add_argument("--dense-url", default="http://127.0.0.1:7861")
    parser.add_argument("--reranker-url", default="http://127.0.0.1:7961")
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--q0-receipt", type=Path, default=DEFAULT_Q0)
    parser.add_argument("--q0-sha256", required=True)
    parser.add_argument("--q6-receipt", type=Path, default=DEFAULT_Q6)
    parser.add_argument("--q6-sha256", required=True)
    parser.add_argument(
        "--q1r-context-archive", type=Path, default=DEFAULT_Q1R_CONTEXTS
    )
    parser.add_argument("--q1r-context-sha256", required=True)
    args = parser.parse_args()

    reader_models = _served_model(args.reader_url)
    dense_models = _served_model(args.dense_url)
    reranker_models = _served_model(args.reranker_url)
    dense_identity = {
        "model_id": "BAAI/bge-m3",
        "served_model_name": "bge-m3",
        "revision": "LOCAL_REVISION_UNAVAILABLE",
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
        "revision": "LOCAL_REVISION_UNAVAILABLE",
        "artifact_sha256": _sha256(RERANK_MODEL_PATH / "model.safetensors"),
        "config_sha256": _sha256(RERANK_MODEL_PATH / "config.json"),
        "max_model_len": 8_192,
        "projection_version": "QUERY_TIME_ONLY_NOT_PERSISTED",
        "endpoint": args.reranker_url,
        "models_response": reranker_models,
        "process": _process_identity(7961),
    }
    dense = VllmDenseClient(
        args.dense_url,
        model_id="bge-m3",
        artifact_identity=dense_identity,
    )
    reranker = VllmRerankerClient(
        args.reranker_url,
        model_id="bge-reranker",
        artifact_identity=reranker_identity,
    )
    provider = MatchedVllmProvider(args.reader_url)
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    receipt = run(
        run_id=args.run_id,
        output_root=output_root,
        q0_receipt=args.q0_receipt,
        q0_sha256=args.q0_sha256,
        q6_receipt=args.q6_receipt,
        q6_sha256=args.q6_sha256,
        q1r_context_archive=args.q1r_context_archive,
        q1r_context_sha256=args.q1r_context_sha256,
        dense=dense,
        reranker=reranker,
        provider=provider,
        token_count=_local_token_counter(args.tokenizer),
        index_text_projector=_dense_index_projector(
            DENSE_MODEL_PATH / "tokenizer.json"
        ),
        execution_identity={
            "hostname": platform.node(),
            "gpu": _gpu_identity(),
            "reader": {
                "model_id": MODEL_ID,
                "endpoint": args.reader_url,
                "models_response": reader_models,
                "process": _process_identity(7860),
                "provider_contract": full_provider_contract(),
            },
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
                "summaries": receipt["summaries"],
                "decision": receipt["decision"],
                "efficiency": receipt["efficiency"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
