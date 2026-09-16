"""Frozen BEAM pair-chunk dense-RAG context runner.

The implementation mirrors the benchmark-native retrieval path without importing
BEAM's answer-generation module (which also initializes unrelated providers).  It
does not read probing-question labels and never calls an answer or judge model.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
from tokenizers import Tokenizer

from evals.paper.contracts import (
    ContextRecord,
    read_context_archive,
    write_context_archive,
)
from evals.paper.datasets.extended import (
    ExtendedCase,
    ExtendedSession,
    load_beam_inputs,
)
from evals.paper.freeze import DEFAULT_MANIFEST, require_paper_evaluation_ready
from evals.paper.identity import sha256_file, source_inventory

ROOT = Path(__file__).resolve().parents[3]
BEAM_ROOT = Path("/cra/memory/mx_memory/benchmarks/BEAM")
DEFAULT_INPUTS = ROOT / "var/dg11/paper/freeze/beam-128k-inputs.json"
DEFAULT_TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
MODEL_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
MODEL_ID = f"BAAI/bge-small-en-v1.5@{MODEL_REVISION}"
DEFAULT_MODEL = (
    ROOT
    / "var/dg11/paper/models/BAAI--bge-small-en-v1.5--5c38ec7c"
)
OFFICIAL_SOURCE = (
    BEAM_ROOT / "src/answer_probing_questions/long_term_memory_methods.py"
)
EXPECTED_OFFICIAL_SOURCE_SHA256 = (
    "d3fd96786d2d58a4b0b60ff726ebf00d1adf84f7bb8487abfd8768f3519cffd8"
)
EXPECTED_WEIGHTS_SHA256 = (
    "3c9f31665447c8911517620762200d2245a2518d6e7208acc78cd9db317e21ad"
)
EXPECTED_TOKENIZER_SHA256 = (
    "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"
)
EXPECTED_CONFIG_SHA256 = (
    "094f8e891b932f2000c92cfc663bac4c62069f5d8af5b5278c4306aef3084750"
)
EXPECTED_SENTENCE_TRANSFORMERS = "5.0.0"
EXPECTED_FAISS = "1.11.0"
EXPECTED_TORCH = "2.7.1+cu126"
EXPECTED_TRANSFORMERS = "4.54.1"
METHOD_ID = "BEAM-DENSE-RAG"
TOP_K = 5


class BeamDenseContextError(RuntimeError):
    pass


@dataclass(frozen=True)
class _PairChunk:
    source_id: str
    text: str


def _history_id(sessions: tuple[ExtendedSession, ...]) -> str:
    return "beam-history-" + hashlib.sha256(
        "\0".join(session.session_id for session in sessions).encode()
    ).hexdigest()[:20]


def _official_pair_chunks(
    sessions: tuple[ExtendedSession, ...],
) -> tuple[_PairChunk, ...]:
    """Mirror BEAM ``create_chunking(..., retrieval_method='pair_chunk')``."""

    chunks: list[_PairChunk] = []
    for session in sessions:
        turns = session.turns
        if len(turns) % 2:
            raise BeamDenseContextError("BEAM pair_chunk received an odd message count")
        for pair_ordinal in range(0, len(turns), 2):
            user, assistant = turns[pair_ordinal : pair_ordinal + 2]
            if user.role != "user" or assistant.role != "assistant":
                raise BeamDenseContextError("BEAM pair_chunk role order drifted")
            # Preserve the whitespace in the benchmark's native f-string: it is
            # model-visible input to the official embedding model.
            text = f"""
                                    USER: {user.content} \n\n
                                    ASSISTANT: {assistant.content}
                                    """
            chunks.append(
                _PairChunk(
                    source_id=f"{session.session_id}:pair-{pair_ordinal // 2:03d}",
                    text=text,
                )
            )
    if not chunks:
        raise BeamDenseContextError("BEAM history produced no pair chunks")
    return tuple(chunks)


def _fit_prefix(
    value: str, token_budget: int, tokenizer: Tokenizer
) -> tuple[str, bool]:
    if token_budget <= 0:
        raise BeamDenseContextError("BEAM context token budget must be positive")
    counter = lambda text: len(tokenizer.encode(text).ids)
    if counter(value) <= token_budget:
        return value, False
    low = 0
    high = len(value)
    best = ""
    while low <= high:
        midpoint = (low + high) // 2
        candidate = value[:midpoint].rstrip()
        if counter(candidate) <= token_budget:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    return best, True


class _FrozenBGE:
    def __init__(self, model_path: Path, *, device: str) -> None:
        if sha256_file(OFFICIAL_SOURCE) != EXPECTED_OFFICIAL_SOURCE_SHA256:
            raise BeamDenseContextError("BEAM official dense source drifted")
        expected = {
            "config.json": EXPECTED_CONFIG_SHA256,
            "model.safetensors": EXPECTED_WEIGHTS_SHA256,
            "tokenizer.json": EXPECTED_TOKENIZER_SHA256,
        }
        if any(
            not (model_path / name).is_file()
            or sha256_file(model_path / name) != digest
            for name, digest in expected.items()
        ):
            raise BeamDenseContextError("BEAM BGE snapshot identity drifted")
        sentence_transformers = importlib.import_module("sentence_transformers")
        faiss = importlib.import_module("faiss")
        torch = importlib.import_module("torch")
        transformers = importlib.import_module("transformers")
        observed = {
            "faiss": str(faiss.__version__),
            "sentence_transformers": str(sentence_transformers.__version__),
            "torch": str(torch.__version__),
            "transformers": str(transformers.__version__),
        }
        expected_versions = {
            "faiss": EXPECTED_FAISS,
            "sentence_transformers": EXPECTED_SENTENCE_TRANSFORMERS,
            "torch": EXPECTED_TORCH,
            "transformers": EXPECTED_TRANSFORMERS,
        }
        if observed != expected_versions:
            raise BeamDenseContextError("BEAM dense dependency identity drifted")
        if device != "cpu" and not bool(torch.cuda.is_available()):
            raise BeamDenseContextError("requested BEAM CUDA device is unavailable")
        self._faiss: Any = faiss
        self._model: Any = sentence_transformers.SentenceTransformer(
            str(model_path), device=device, local_files_only=True
        )
        self._lock = threading.RLock()
        self.embedding_calls = 0
        self.embedding_items = 0
        self.model_path = model_path
        self.device = device
        self.versions = observed

    def encode(self, values: list[str]) -> np.ndarray:
        if not values or any(not isinstance(value, str) for value in values):
            raise BeamDenseContextError("BEAM BGE received an invalid text batch")
        # BEAM's safe_encode serializes first-party SentenceTransformer calls.
        with self._lock:
            vectors = self._model.encode(
                values,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            self.embedding_calls += 1
            self.embedding_items += len(values)
        array = np.asarray(vectors, dtype=np.float32)
        if array.ndim != 2 or array.shape[0] != len(values):
            raise BeamDenseContextError("BEAM BGE returned an invalid embedding shape")
        if not np.isfinite(array).all():
            raise BeamDenseContextError("BEAM BGE returned non-finite embeddings")
        return array

    def index(self, vectors: np.ndarray) -> Any:
        index = self._faiss.IndexFlatL2(int(vectors.shape[1]))
        index.add(np.ascontiguousarray(vectors, dtype=np.float32))
        return index

    def identity(self) -> dict[str, Any]:
        inventory = source_inventory(self.model_path)
        return {
            "config_sha256": EXPECTED_CONFIG_SHA256,
            "device": self.device,
            "faiss_index": "IndexFlatL2",
            "model_id": MODEL_ID,
            "model_inventory_root_sha256": inventory["inventory_root_sha256"],
            "model_inventory_total_bytes": inventory["total_bytes"],
            "normalization": "normalize_embeddings=True",
            "official_source_sha256": EXPECTED_OFFICIAL_SOURCE_SHA256,
            "pair_chunk": True,
            "python": platform.python_version(),
            "tokenizer_sha256": EXPECTED_TOKENIZER_SHA256,
            "top_k": TOP_K,
            "versions": self.versions,
            "weights_sha256": EXPECTED_WEIGHTS_SHA256,
        }


def _query_record(
    *,
    case: ExtendedCase,
    chunks: tuple[_PairChunk, ...],
    index: Any,
    embedder: _FrozenBGE,
    tokenizer: Tokenizer,
    token_budget: int,
) -> ContextRecord:
    started = time.perf_counter()
    query_vector = embedder.encode([case.question])
    distances, indices = index.search(query_vector, min(TOP_K, len(chunks)))
    selected = [chunks[int(index_value)] for index_value in indices[0]]
    rendered = "".join(chunk.text for chunk in selected)
    context, truncated = _fit_prefix(rendered, token_budget, tokenizer)
    contributing: list[_PairChunk] = []
    consumed = 0
    for chunk in selected:
        if consumed < len(context):
            contributing.append(chunk)
        consumed += len(chunk.text)
    trace = tuple(
        {
            "distance": round(float(distance), 9),
            "rank": rank,
            "source_id": chunk.source_id,
        }
        for rank, (distance, chunk) in enumerate(
            zip(distances[0], selected, strict=True), start=1
        )
    )
    return ContextRecord(
        case_id=case.case_id,
        method_id=METHOD_ID,
        track="NATIVE",
        context=context,
        source_ids=tuple(chunk.source_id for chunk in contributing),
        trace=trace,
        declared_tokens=len(tokenizer.encode(context).ids),
        latency_ms=(time.perf_counter() - started) * 1000,
        usage={
            "answer_calls": 0,
            "context_truncated": truncated,
            "embedding_calls": 1,
            "embedding_items": 1,
            "ingest_extraction_calls": 0,
            "judge_calls": 0,
            "memory_query_model_calls": 0,
            "reflection_consolidation_calls": 0,
            "retriever_calls": 1,
            "retrieved_chunks": len(selected),
        },
    )


def _history_records(
    *,
    cases: list[ExtendedCase],
    embedder: _FrozenBGE,
    tokenizer: Tokenizer,
    token_budget: int,
) -> tuple[list[ContextRecord], dict[str, Any]]:
    history_started = time.perf_counter()
    chunks = _official_pair_chunks(cases[0].sessions)
    calls_before = embedder.embedding_calls
    items_before = embedder.embedding_items
    index_started = time.perf_counter()
    vectors = embedder.encode([chunk.text for chunk in chunks])
    index = embedder.index(vectors)
    index_latency_ms = (time.perf_counter() - index_started) * 1000
    records = [
        _query_record(
            case=case,
            chunks=chunks,
            index=index,
            embedder=embedder,
            tokenizer=tokenizer,
            token_budget=token_budget,
        )
        for case in cases
    ]
    return records, {
        "chunk_count": len(chunks),
        "embedding_calls": embedder.embedding_calls - calls_before,
        "embedding_items": embedder.embedding_items - items_before,
        "history_id": _history_id(cases[0].sessions),
        "index_latency_ms": round(index_latency_ms, 6),
        "question_count": len(cases),
        "status": "SUCCEEDED",
        "wall_time_ms": round((time.perf_counter() - history_started) * 1000, 6),
    }


def _failure_records(
    cases: list[ExtendedCase], exc: Exception, *, attempts: int
) -> tuple[list[ContextRecord], dict[str, Any]]:
    message_sha = hashlib.sha256(str(exc).encode()).hexdigest()
    records = [
        ContextRecord(
            case_id=case.case_id,
            method_id=METHOD_ID,
            track="NATIVE",
            context="",
            source_ids=(),
            trace=(),
            declared_tokens=0,
            latency_ms=0,
            usage={
                "answer_calls": 0,
                "attempts": attempts,
                "failure_class": type(exc).__name__,
                "failure_message_sha256": message_sha,
                "judge_calls": 0,
            },
            terminal_status="INFRASTRUCTURE_FAILURE",
        )
        for case in cases
    ]
    return records, {
        "attempts": attempts,
        "failure_class": type(exc).__name__,
        "failure_message_sha256": message_sha,
        "history_id": _history_id(cases[0].sessions),
        "question_count": len(cases),
        "status": "INFRASTRUCTURE_FAILURE",
    }


def _identity(
    *, run_id: str, input_path: Path, model_path: Path, tokenizer_path: Path
) -> dict[str, Any]:
    return {
        "input_sha256": sha256_file(input_path),
        "method_id": METHOD_ID,
        "model_revision": MODEL_REVISION,
        "official_source_sha256": EXPECTED_OFFICIAL_SOURCE_SHA256,
        "run_id": run_id,
        "runner_sha256": sha256_file(Path(__file__)),
        "tokenizer_sha256": sha256_file(tokenizer_path),
        "weights_sha256": sha256_file(model_path / "model.safetensors"),
    }


def _checkpoint(
    path: Path,
    *,
    identity: dict[str, Any],
    expected_ids: set[str],
) -> tuple[dict[str, ContextRecord], list[dict[str, Any]]]:
    if not path.exists():
        return {}, []
    envelope = json.loads(path.read_text(encoding="utf-8"))
    records = read_context_archive(path)
    stats = envelope.get("history_stats") if isinstance(envelope, dict) else None
    if (
        not isinstance(envelope, dict)
        or envelope.get("worker_identity") != identity
        or not isinstance(stats, list)
        or not {record.case_id for record in records}.issubset(expected_ids)
        or len({record.case_id for record in records}) != len(records)
    ):
        raise BeamDenseContextError("BEAM dense checkpoint drifted")
    return {record.case_id: record for record in records}, list(stats)


def run(
    *,
    run_id: str,
    input_path: Path,
    output: Path,
    model_path: Path,
    tokenizer_path: Path,
    token_budget: int,
    workers: int,
    max_history_attempts: int,
    device: str,
    freeze_manifest: Path,
    allow_unfrozen_smoke: bool,
) -> dict[str, Any]:
    if output.exists():
        raise BeamDenseContextError("BEAM dense output is write-once")
    if workers not in {1, 2} or max_history_attempts not in {1, 2}:
        raise BeamDenseContextError("BEAM dense concurrency/attempt bound is invalid")
    if device != "cpu" and device not in {"cuda:2", "cuda:3"}:
        raise BeamDenseContextError("BEAM dense device is outside the isolated set")
    partition, cases = load_beam_inputs(input_path)
    if allow_unfrozen_smoke:
        if "SMOKE" not in partition:
            raise BeamDenseContextError("unfrozen BEAM dense run requires smoke inputs")
    else:
        require_paper_evaluation_ready(freeze_manifest)
        histories = {_history_id(case.sessions) for case in cases}
        if partition != "BEAM-128K-FULL" or len(cases) != 400 or len(histories) != 20:
            raise BeamDenseContextError("formal BEAM dense denominator drifted")
    if token_budget <= 0:
        raise BeamDenseContextError("BEAM dense token budget must be positive")
    identity = _identity(
        run_id=run_id,
        input_path=input_path,
        model_path=model_path,
        tokenizer_path=tokenizer_path,
    )
    checkpoint_path = output.with_suffix(output.suffix + ".partial")
    expected_ids = {case.case_id for case in cases}
    records_by_id, history_stats = _checkpoint(
        checkpoint_path, identity=identity, expected_ids=expected_ids
    )
    completed_histories = {
        str(item["history_id"])
        for item in history_stats
        if isinstance(item, dict) and isinstance(item.get("history_id"), str)
    }
    by_history: dict[str, list[ExtendedCase]] = defaultdict(list)
    for case in cases:
        by_history[_history_id(case.sessions)].append(case)
    pending = [
        history_cases
        for history_id, history_cases in by_history.items()
        if history_id not in completed_histories
    ]
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    embedder = _FrozenBGE(model_path, device=device)

    def execute(history_cases: list[ExtendedCase]) -> tuple[list[ContextRecord], dict[str, Any]]:
        last_failure: Exception | None = None
        for attempt in range(1, max_history_attempts + 1):
            try:
                records, stats = _history_records(
                    cases=history_cases,
                    embedder=embedder,
                    tokenizer=tokenizer,
                    token_budget=token_budget,
                )
                stats["attempts"] = attempt
                return records, stats
            except Exception as exc:  # noqa: BLE001 - bounded terminal policy
                last_failure = exc
        assert last_failure is not None
        return _failure_records(
            history_cases, last_failure, attempts=max_history_attempts
        )

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="beam-dense") as pool:
        futures = {pool.submit(execute, history_cases): history_cases for history_cases in pending}
        for future in as_completed(futures):
            history_records, stat = future.result()
            records_by_id.update({record.case_id: record for record in history_records})
            history_stats.append(stat)
            ordered_partial = [
                records_by_id[case.case_id]
                for case in cases
                if case.case_id in records_by_id
            ]
            write_context_archive(
                checkpoint_path,
                run_id=run_id,
                benchmark_id=partition,
                records=ordered_partial,
                metadata={
                    "history_stats": sorted(history_stats, key=lambda item: str(item["history_id"])),
                    "paper_labels_opened": False,
                    "worker_identity": identity,
                },
            )
    if set(records_by_id) != expected_ids:
        raise BeamDenseContextError("BEAM dense terminal denominator is incomplete")
    records = tuple(records_by_id[case.case_id] for case in cases)
    failures = sum(record.terminal_status != "SUCCEEDED" for record in records)
    payload = write_context_archive(
        output,
        run_id=run_id,
        benchmark_id=partition,
        records=records,
        metadata={
            "answer_calls": 0,
            "development_ai_reviews": 0,
            "embedder_identity": embedder.identity(),
            "embedding_calls": embedder.embedding_calls,
            "embedding_items": embedder.embedding_items,
            "failure_count": failures,
            "history_count": len(by_history),
            "history_reuse": True,
            "history_stats": sorted(history_stats, key=lambda item: str(item["history_id"])),
            "judge_calls": 0,
            "labels_accessed": False,
            "maximum_concurrent_requests": workers,
            "paper_labels_opened": False,
            "status": "PASS" if failures == 0 else "FAIL",
            "token_budget": token_budget,
            "worker_identity": identity,
        },
    )
    checkpoint_path.unlink(missing_ok=True)
    return cast(dict[str, Any], payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--token-budget", type=int, default=512)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--max-history-attempts", type=int, choices=(1, 2), default=1)
    parser.add_argument("--device", choices=("cpu", "cuda:2", "cuda:3"), default="cpu")
    parser.add_argument("--freeze-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--allow-unfrozen-smoke", action="store_true")
    args = parser.parse_args()
    result = run(
        run_id=args.run_id,
        input_path=args.inputs.resolve(),
        output=args.output.resolve(),
        model_path=args.model.resolve(),
        tokenizer_path=args.tokenizer.resolve(),
        token_budget=args.token_budget,
        workers=args.workers,
        max_history_attempts=args.max_history_attempts,
        device=args.device,
        freeze_manifest=args.freeze_manifest.resolve(),
        allow_unfrozen_smoke=args.allow_unfrozen_smoke,
    )
    print(
        json.dumps(
            {
                "failure_count": result["failure_count"],
                "record_count": result["record_count"],
                "status": result["status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
