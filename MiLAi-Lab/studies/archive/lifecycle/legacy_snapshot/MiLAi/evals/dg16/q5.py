"""DG-16 Q5 strong dense/reranker single-factor ablation."""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, cast

import numpy as np

from evals.dg14.benchmark import (
    OPENED_DEV_CASE_IDS,
    OPENED_DEV_INPUT_PATH,
    OpenedDevCase,
    load_opened_dev,
)
from evals.dg16.q0 import load_evaluation_fixture
from evals.dg16.q4 import (
    TOKEN_BUDGET,
    EvidenceUnit,
    Q4Provider,
    _fit_context,
    _query_spec_receipt,
    build_units,
)
from evals.paper.adapters.baselines import _bm25_scores
from evals.paper.scorers.longmemeval import score_answer

METHODS = ("FTS", "FTS_DENSE", "FTS_RERANK", "FTS_DENSE_RERANK")
CANDIDATE_CAP = 20
CONTEXT_UNIT_CAP = 3
RRF_K = 60


class DenseRetriever(Protocol):
    identity: dict[str, Any]

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...

    def metrics(self) -> Mapping[str, Any]: ...


class Reranker(Protocol):
    identity: dict[str, Any]

    def rerank(
        self, query: str, documents: Sequence[str], *, top_n: int
    ) -> list[tuple[int, float]]: ...

    def metrics(self) -> Mapping[str, Any]: ...


TokenCounter = Callable[[str], int]


def _post_retrieval_json(
    base_url: str, path: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    if path not in {"/v1/embeddings", "/v1/rerank"}:
        raise ValueError("Q5 retrieval client path is not allowlisted")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            raw = response.read(64 * 1024 * 1024 + 1)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Q5 retrieval endpoint failed: {path}") from exc
    if len(raw) > 64 * 1024 * 1024:
        raise RuntimeError("Q5 retrieval response exceeded 64 MiB")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise TypeError("Q5 retrieval response must be an object")
    return parsed


class VllmDenseClient:
    def __init__(
        self,
        base_url: str,
        *,
        model_id: str,
        artifact_identity: Mapping[str, Any],
        batch_size: int = 64,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id
        self.batch_size = batch_size
        self.identity = dict(artifact_identity)
        self._calls = 0
        self._logical_items = 0
        self._latency_ms = 0.0

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            began = time.perf_counter()
            response = _post_retrieval_json(
                self.base_url,
                "/v1/embeddings",
                {"model": self.model_id, "input": batch},
            )
            self._latency_ms += (time.perf_counter() - began) * 1_000
            self._calls += 1
            self._logical_items += len(batch)
            raw_data = response.get("data")
            if not isinstance(raw_data, list) or len(raw_data) != len(batch):
                raise RuntimeError("dense embedding response cardinality drifted")
            ordered = sorted(raw_data, key=lambda item: int(item["index"]))
            for item in ordered:
                vector = item.get("embedding")
                if not isinstance(vector, list) or not vector:
                    raise RuntimeError("dense embedding response lacks a vector")
                vectors.append([float(value) for value in vector])
        matrix = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise RuntimeError("dense embedding response contains a zero vector")
        return cast(np.ndarray, matrix / norms)

    def metrics(self) -> Mapping[str, Any]:
        return {
            "physical_calls": self._calls,
            "logical_items": self._logical_items,
            "latency_ms": round(self._latency_ms, 6),
        }


class VllmRerankerClient:
    def __init__(
        self,
        base_url: str,
        *,
        model_id: str,
        artifact_identity: Mapping[str, Any],
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id
        self.identity = dict(artifact_identity)
        self._calls = 0
        self._pairs = 0
        self._latency_ms = 0.0

    def rerank(
        self, query: str, documents: Sequence[str], *, top_n: int
    ) -> list[tuple[int, float]]:
        began = time.perf_counter()
        response = _post_retrieval_json(
            self.base_url,
            "/v1/rerank",
            {
                "model": self.model_id,
                "query": query,
                "documents": list(documents),
                "top_n": top_n,
            },
        )
        self._latency_ms += (time.perf_counter() - began) * 1_000
        self._calls += 1
        self._pairs += len(documents)
        raw_results = response.get("results")
        if not isinstance(raw_results, list) or len(raw_results) != top_n:
            raise RuntimeError("reranker response cardinality drifted")
        return [
            (int(item["index"]), float(item["relevance_score"]))
            for item in raw_results
        ]

    def metrics(self) -> Mapping[str, Any]:
        return {
            "physical_calls": self._calls,
            "logical_pairs": self._pairs,
            "latency_ms": round(self._latency_ms, 6),
        }


def _rank_desc(values: Sequence[float]) -> list[int]:
    return sorted(range(len(values)), key=lambda index: (values[index], index), reverse=True)


def _rrf(left: Sequence[int], right: Sequence[int]) -> list[int]:
    scores: dict[int, float] = {}
    for ranking in (left, right):
        for rank, index in enumerate(ranking, start=1):
            scores[index] = scores.get(index, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores, key=lambda index: (scores[index], index), reverse=True)


def _selected_units(
    case: OpenedDevCase,
    method: str,
    *,
    dense: DenseRetriever,
    reranker: Reranker,
    corpus_vectors: np.ndarray,
    query_vector: np.ndarray,
) -> tuple[list[EvidenceUnit], dict[str, Any]]:
    units = list(build_units(case, "CHUNK"))
    bm25_scores = _bm25_scores(
        [unit.index_text.split(" ") for unit in units], case.question.split(" ")
    )
    bm25_rank = _rank_desc(bm25_scores)
    dense_scores = corpus_vectors @ query_vector
    dense_rank = _rank_desc(dense_scores.tolist())
    base_rank = _rrf(bm25_rank, dense_rank) if "DENSE" in method else bm25_rank
    candidate_indices = base_rank[:CANDIDATE_CAP]
    reranker_scores: dict[int, float] = {}
    if "RERANK" in method:
        reranked = reranker.rerank(
            case.question,
            [units[index].content for index in candidate_indices],
            top_n=min(CONTEXT_UNIT_CAP, len(candidate_indices)),
        )
        selected_indices = [candidate_indices[index] for index, _score in reranked]
        reranker_scores = {
            candidate_indices[index]: score for index, score in reranked
        }
    else:
        selected_indices = candidate_indices[:CONTEXT_UNIT_CAP]
    selected = [units[index] for index in selected_indices]
    selected.sort(key=lambda unit: (unit.observed_at, unit.session_ordinal, unit.unit_id))
    trace = {
        "bm25_candidate_count": len(units),
        "candidate_cap": CANDIDATE_CAP,
        "context_unit_cap": CONTEXT_UNIT_CAP,
        "dense_enabled": "DENSE" in method,
        "reranker_enabled": "RERANK" in method,
        "dense_model_id": dense.identity["model_id"] if "DENSE" in method else None,
        "reranker_model_id": (
            reranker.identity["model_id"] if "RERANK" in method else None
        ),
        "selected": [
            {
                "unit_id": units[index].unit_id,
                "bm25_score": bm25_scores[index],
                "dense_score": float(dense_scores[index]),
                "reranker_score": reranker_scores.get(index),
            }
            for index in selected_indices
        ],
    }
    return selected, trace


def build_q5_contexts(
    cases: Sequence[OpenedDevCase],
    *,
    dense: DenseRetriever,
    reranker: Reranker,
    token_count: TokenCounter,
) -> list[dict[str, Any]]:
    """Build contexts before evaluation labels become available."""

    records: list[dict[str, Any]] = []
    for case in cases:
        units = build_units(case, "CHUNK")
        dense_started = time.perf_counter()
        corpus_vectors = dense.embed([unit.index_text for unit in units])
        query_vector = dense.embed([case.question])[0]
        dense_case_latency_ms = (time.perf_counter() - dense_started) * 1_000
        for method in METHODS:
            started = time.perf_counter()
            selected, trace = _selected_units(
                case,
                method,
                dense=dense,
                reranker=reranker,
                corpus_vectors=corpus_vectors,
                query_vector=query_vector,
            )
            context, truncated = _fit_context(selected, TOKEN_BUDGET, token_count)
            records.append(
                {
                    "case_id": case.case_id,
                    "method": method,
                    "context": context,
                    "context_tokens": token_count(context),
                    "context_truncated": truncated,
                    "selected_units": [unit.unit_id for unit in selected],
                    "selected_session_ids": [unit.session_id for unit in selected],
                    "selected_turn_refs": [
                        turn_ref for unit in selected for turn_ref in unit.turn_refs
                    ],
                    "retrieval_trace": trace,
                    "retrieval_latency_ms": round(
                        (time.perf_counter() - started) * 1_000
                        + (dense_case_latency_ms if "DENSE" in method else 0.0),
                        6,
                    ),
                }
            )
    return records


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return round(ordered[index], 6)


def run_q5_ablation(
    *,
    run_id: str,
    dense: DenseRetriever,
    reranker: Reranker,
    provider: Q4Provider,
    token_count: TokenCounter,
    execution_identity: Mapping[str, Any],
) -> dict[str, Any]:
    _partition, cases = load_opened_dev(OPENED_DEV_INPUT_PATH)
    if tuple(case.case_id for case in cases) != OPENED_DEV_CASE_IDS:
        raise RuntimeError("Q5 opened-development case order drifted")
    context_records = build_q5_contexts(
        cases, dense=dense, reranker=reranker, token_count=token_count
    )
    fixture = load_evaluation_fixture(cases=cases)
    labels = {item["case_id"]: item for item in fixture["cases"]}
    case_index = {case.case_id: case for case in cases}
    records: list[dict[str, Any]] = []
    for record in context_records:
        case = case_index[record["case_id"]]
        label = labels[case.case_id]
        atoms = label["required_atoms"]
        atom_hits = [atom["span"]["text"] in record["context"] for atom in atoms]
        result = provider.answer(
            run_id=run_id,
            case_id=case.case_id,
            method_id=f"DG16-Q5-{record['method']}",
            question=case.question,
            question_as_of=case.question_at,
            memory_context=record["context"],
            token_budget=TOKEN_BUDGET,
        )
        records.append(
            {
                **record,
                "query_spec": _query_spec_receipt(case),
                "required_atom_count": len(atoms),
                "atom_hits": atom_hits,
                "answer_bearing_recall": sum(atom_hits) / len(atoms),
                "evidence_set_complete": all(atom_hits),
                "prediction": result.answer,
                "score": score_answer(result.answer, label["answers"]),
                "reader": {
                    "prompt_sha256": result.prompt_sha256,
                    "prompt_tokens": result.prompt_tokens,
                    "memory_tokens": result.memory_tokens,
                    "completion_tokens": result.completion_tokens,
                    "provider_latency_ms": result.provider_latency_ms,
                    "provider_calls": result.provider_calls,
                },
            }
        )
    summaries: dict[str, dict[str, Any]] = {}
    for method in METHODS:
        selected = [record for record in records if record["method"] == method]
        total_atoms = sum(record["required_atom_count"] for record in selected)
        summaries[method] = {
            "case_count": len(selected),
            "answer_bearing_recall": sum(
                sum(record["atom_hits"]) for record in selected
            )
            / total_atoms,
            "evidence_set_completeness": sum(
                record["evidence_set_complete"] for record in selected
            )
            / len(selected),
            "reader_exact_match": sum(
                record["score"]["exact_match"] for record in selected
            )
            / len(selected),
            "reader_normalized_f1": sum(
                record["score"]["normalized_f1"] for record in selected
            )
            / len(selected),
            "retrieval_p95_ms": _percentile(
                [record["retrieval_latency_ms"] for record in selected], 0.95
            ),
            "mean_context_tokens": sum(
                record["context_tokens"] for record in selected
            )
            / len(selected),
            "paired_case_outcomes": {
                record["case_id"]: record["score"]["exact_match"]
                for record in selected
            },
        }
    return {
        "schema": "milai.dg16.q5-strong-retrieval-ablation.v1",
        "status": "SUCCEEDED",
        "classification": "OPENED_DEVELOPMENT_ONLY / EVALUATION_PLANE",
        "formal_holdout_consumed": False,
        "label_fields_available_to_product_path": False,
        "run_id": run_id,
        "case_count": len(cases),
        "cell_count": len(records),
        "methods": list(METHODS),
        "fixed_controls": {
            "evidence_unit": "CHUNK",
            "evidence_unit_projection": "dg16-q5-chunk-1600b-v1",
            "candidate_cap": CANDIDATE_CAP,
            "context_unit_cap": CONTEXT_UNIT_CAP,
            "context_token_budget": TOKEN_BUDGET,
            "rrf_k": RRF_K,
            "reader_prompt": "FROZEN_DG14",
            "query_spec_by_case": {
                case.case_id: _query_spec_receipt(case) for case in cases
            },
        },
        "dense": {"identity": dict(dense.identity), "metrics": dict(dense.metrics())},
        "reranker": {
            "identity": dict(reranker.identity),
            "metrics": dict(reranker.metrics()),
        },
        "execution_identity": dict(execution_identity),
        "records": records,
        "summaries": summaries,
        "decision": {
            "best_method": max(
                METHODS,
                key=lambda method: (
                    summaries[method]["reader_exact_match"],
                    summaries[method]["evidence_set_completeness"],
                    summaries[method]["answer_bearing_recall"],
                ),
            ),
            "production_default_frozen": False,
            "reason": "N=5 opened-development single-factor ablation only",
        },
    }


__all__ = [
    "METHODS",
    "VllmDenseClient",
    "VllmRerankerClient",
    "build_q5_contexts",
    "run_q5_ablation",
]
