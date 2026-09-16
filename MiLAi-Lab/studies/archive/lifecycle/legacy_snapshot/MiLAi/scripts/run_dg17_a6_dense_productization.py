#!/usr/bin/env python3
"""Run the DG-17 A6 label-separated Raw Evidence dense matched evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from milai.adapters import ProjectionIdentity
from milai.application.evidence_dense import evidence_turn_embedding_text

from evals.dg16.lme10 import load_public_dev_cases
from evals.dg16.q4 import build_units
from evals.dg16.q5 import VllmDenseClient
from evals.dg17.a6_dense_productization import (
    A6DenseError,
    build_a6_label_free_archive,
    build_a6_receipt,
    estimate_a6_work,
    score_a6_archive,
)

DEFAULT_OUTPUT_ROOT = ROOT / "var/dg17/a6"
DEFAULT_GOAL = ROOT / "MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md"
DEFAULT_FOCUSED_POSTGRES = (
    ROOT
    / "var/dg17/a6/dg17-a6-evidence-dense-20260827-004/focused-postgres-001.json"
)
DEFAULT_FOCUSED_POSTGRES_SHA256 = (
    "1799a251896281336b67f7475590953a5e26295dac625251a8fcbb97c51636a1"
)
DEFAULT_Q8 = (
    ROOT / "var/dg17/q8/dg17-q8-retrieval-ablation-20260827-002/receipt.json"
)
DEFAULT_Q8_SHA256 = "ca4c5dde4bd348f7fe860165c6b7ab4136ce776757864b355e8774dd6e8326ef"
DENSE_ARTIFACT_ROOT = Path("/data/models/embed")
SOURCE_DIMENSIONS = 1_024
PROJECTION_DIMENSIONS = 128
EMBEDDING_BATCH_SIZE = 64
MAX_MODEL_TOKENS = 8_192


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--dense-url", default="http://127.0.0.1:7861")
    parser.add_argument("--served-model-name", default="bge-m3")
    parser.add_argument("--goal", type=Path, default=DEFAULT_GOAL)
    parser.add_argument(
        "--focused-postgres-receipt", type=Path, default=DEFAULT_FOCUSED_POSTGRES
    )
    parser.add_argument(
        "--focused-postgres-sha256", default=DEFAULT_FOCUSED_POSTGRES_SHA256
    )
    parser.add_argument("--q8-receipt", type=Path, default=DEFAULT_Q8)
    parser.add_argument("--q8-sha256", default=DEFAULT_Q8_SHA256)
    args = parser.parse_args()

    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    if output_root.exists():
        raise A6DenseError("A6 output exists; choose a fresh run ID")
    output_root.mkdir(parents=True)
    cases, selection = load_public_dev_cases()
    work = estimate_a6_work(cases)
    _assert_sha(args.focused_postgres_receipt, args.focused_postgres_sha256)
    _assert_sha(args.q8_receipt, args.q8_sha256)
    served_models = _served_models(args.dense_url)
    served_ids = {
        str(item.get("id"))
        for item in served_models["data"]
        if isinstance(item, dict)
    }
    if args.served_model_name not in served_ids:
        raise A6DenseError("A6 expected embedding model is not served")
    tokenizer_path = DENSE_ARTIFACT_ROOT / "tokenizer.json"
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    token_lengths = [
        len(
            tokenizer.encode(
                evidence_turn_embedding_text(unit.index_text),
                add_special_tokens=False,
            ).ids
        )
        for case in cases
        for unit in build_units(case, "TURN")
    ]
    maximum_input_tokens = max(token_lengths)
    if maximum_input_tokens > MAX_MODEL_TOKENS:
        raise A6DenseError("A6 bounded embedding input exceeds served model limit")

    projection_identity = ProjectionIdentity(
        provider="vllm_openai_embeddings",
        model_id="BAAI/bge-m3",
        source_dimensions=SOURCE_DIMENSIONS,
        projection_dimensions=PROJECTION_DIMENSIONS,
        normalization="source-l2+signed-projection-l2",
        code_version="projection-128/v1",
    )
    dense_identity = {
        "provider": projection_identity.provider,
        "model_id": projection_identity.model_id,
        "served_model_name": args.served_model_name,
        "endpoint": args.dense_url,
        "source_dimensions": SOURCE_DIMENSIONS,
        "projection_dimensions": PROJECTION_DIMENSIONS,
        "projection_identity_key": projection_identity.key,
        "embedding_input_identity": "evidence-turn-utf8-prefix-32768-v1",
        "artifact_sha256": _sha256(DENSE_ARTIFACT_ROOT / "pytorch_model.bin"),
        "config_sha256": _sha256(DENSE_ARTIFACT_ROOT / "config.json"),
        "tokenizer_sha256": _sha256(tokenizer_path),
        "max_model_tokens": MAX_MODEL_TOKENS,
        "maximum_observed_input_tokens": maximum_input_tokens,
        "models_response": served_models,
        "process": _process_identity(7861),
    }
    expected_corpus_calls = math.ceil(
        int(work["evidence_turn_count"]) / EMBEDDING_BATCH_SIZE
    )
    expected_query_calls = int(work["executed_dense_probe_count"])
    execution_plan = {
        "schema": "milai.dg17.a6-execution-plan.v0.1",
        "status": "SEALED_BEFORE_EMBEDDING_CALLS",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / EVALUATION_PLANE",
        "run_id": args.run_id,
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "automatic_retries": 0,
        "reader_calls": 0,
        "reranker_calls": 0,
        "historical_answer_reuse": 0,
        "selection": selection,
        "work": work,
        "call_ledger": {
            "allowed_endpoint": args.dense_url,
            "allowed_served_model": args.served_model_name,
            "embedding_logical_item_ceiling": work[
                "embedding_logical_item_ceiling"
            ],
            "corpus_physical_call_ceiling": expected_corpus_calls,
            "query_physical_call_ceiling": expected_query_calls,
            "total_physical_call_ceiling": expected_corpus_calls
            + expected_query_calls,
            "automatic_retry_ceiling": 0,
        },
        "fixed_controls": {
            "arms": ["FTS_RAW", "FTS_RAW_PLUS_EVIDENCE_DENSE_128"],
            "candidate_cap": 20,
            "primitive_evidence_unit": "LOSSLESS_TURN",
            "fts_baseline": "TOKEN_OVERLAP_PROXY_BOUND_TO_REAL_POSTGRESQL_GATE",
            "fusion_policy": "RRF_K60_PER_SLOT_FTS_PLUS_EVIDENCE_DENSE_V1",
            "event_occurrence_without_projection": "FAIL_CLOSED",
            "same_immutable_snapshot": True,
            "labels_available_to_acquisition": False,
        },
        "bound_artifacts": {
            "goal": _identity(args.goal),
            "focused_postgresql_gate": _identity(args.focused_postgres_receipt),
            "q8_authoritative_diagnostic": _identity(args.q8_receipt),
        },
        "execution_identity": {
            "hostname": platform.node(),
            "embedding": dense_identity,
            "reader": "NOT_CALLED",
            "reranker": "NOT_CALLED",
        },
    }
    execution_plan_path = output_root / "execution-plan.json"
    _atomic_json(execution_plan_path, execution_plan)

    dense = VllmDenseClient(
        args.dense_url,
        model_id=args.served_model_name,
        artifact_identity=dense_identity,
        batch_size=EMBEDDING_BATCH_SIZE,
    )
    started = time.perf_counter()
    try:
        archive = build_a6_label_free_archive(
            cases,
            dense=dense,
            projection_identity=projection_identity,
            run_id=args.run_id,
        )
        metrics = dense.metrics()
        if int(metrics["physical_calls"]) > execution_plan["call_ledger"][
            "total_physical_call_ceiling"
        ]:
            raise A6DenseError("A6 embedding physical-call ceiling exceeded")
        if int(metrics["logical_items"]) > execution_plan["call_ledger"][
            "embedding_logical_item_ceiling"
        ]:
            raise A6DenseError("A6 embedding logical-item ceiling exceeded")
        archive_path = output_root / "label-free-acquisition.json"
        _atomic_json(archive_path, archive)
    except Exception as exc:
        _atomic_json(
            output_root / "failure.json",
            {
                "schema": "milai.dg17.a6-failure.v0.1",
                "run_id": args.run_id,
                "status": "FAIL",
                "stage": "LABEL_FREE_ACQUISITION",
                "automatic_retries": 0,
                "reader_calls": 0,
                "reranker_calls": 0,
                "embedding_metrics": dict(dense.metrics()),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
            },
        )
        raise

    # Labels enter only after the immutable acquisition archive exists on disk.
    from evals.dg17.measurement import load_answer_bearing_labels

    _label_envelope, labeled_cases, labels = load_answer_bearing_labels()
    if tuple(str(case.case_id) for case in labeled_cases) != tuple(
        str(case.case_id) for case in cases
    ):
        raise A6DenseError("A6 scoring case order drifted")
    score = score_a6_archive(archive, labels=labels)
    score_path = output_root / "score.json"
    _atomic_json(score_path, score)
    receipt = build_a6_receipt(
        run_id=args.run_id,
        archive_path=archive_path,
        execution_plan_path=execution_plan_path,
        goal_path=args.goal,
        focused_postgres_receipt=args.focused_postgres_receipt,
        q8_receipt=args.q8_receipt,
        score=score,
        archive=archive,
    )
    receipt["bound_artifacts"]["score"] = _identity(score_path)
    receipt["execution"] = {
        "dense_metrics": dict(dense.metrics()),
        "call_ledger_compliant": True,
        "automatic_retries": 0,
        "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
    }
    receipt_path = output_root / "receipt.json"
    _atomic_json(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(receipt_path.relative_to(ROOT)),
                "receipt_sha256": _sha256(receipt_path),
                "delta": score["delta"],
                "disposition": receipt["disposition"],
                "efficiency": receipt["efficiency"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _served_models(base_url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/models", method="GET"
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise A6DenseError("A6 model identity response exceeded 4 MiB")
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get("data"), list):
        raise A6DenseError("A6 model identity response is malformed")
    return value


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


def _assert_sha(path: Path, expected: str) -> None:
    if _sha256(path) != expected:
        raise A6DenseError(f"A6 bound artifact identity drifted: {path}")


def _identity(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": _sha256(path)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    target = path.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
