from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from evals.dg14.provider import ProviderResult
from evals.dg16.lme10 import load_public_dev_cases, load_public_dev_labels
from evals.dg17.measurement import load_answer_bearing_labels
from evals.dg17.q8_retrieval_ablation import (
    METHODS,
    RETRIEVAL_METHODS,
    TOKEN_BUDGET,
    TYPED_REFERENCE,
    build_q8_contexts,
    build_query_plans,
    contains_forbidden_label_key,
    provider_record,
    score_q8_generations,
)
from scripts.run_dg17_q8_retrieval_ablation import (
    DEFAULT_Q0,
    DEFAULT_Q1R_CONTEXTS,
    DEFAULT_Q6,
    _validate_condition,
    _write_failure,
    _write_progress,
)


class _Dense:
    def __init__(self) -> None:
        self.identity: dict[str, Any] = {"model_id": "fake-bge-m3", "dimensions": 4}
        self.calls = 0
        self.items = 0

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        self.calls += 1
        self.items += len(texts)
        rows: list[np.ndarray[Any, Any]] = []
        for text in texts:
            lowered = text.casefold()
            vector = np.asarray(
                [
                    1.0 + len(lowered) % 17,
                    1.0 + lowered.count("friend"),
                    1.0 + lowered.count("bake"),
                    1.0 + lowered.count("event"),
                ],
                dtype=np.float32,
            )
            rows.append(vector / np.linalg.norm(vector))
        return np.stack(rows)

    def metrics(self) -> dict[str, int]:
        return {"physical_calls": self.calls, "logical_items": self.items}


class _Reranker:
    def __init__(self) -> None:
        self.identity: dict[str, Any] = {"model_id": "fake-reranker"}
        self.calls = 0
        self.pairs = 0

    def rerank(
        self, query: str, documents: Sequence[str], *, top_n: int
    ) -> list[tuple[int, float]]:
        self.calls += 1
        self.pairs += len(documents)
        query_terms = set(query.casefold().split())
        ranked = sorted(
            (
                (
                    index,
                    float(len(query_terms.intersection(document.casefold().split()))),
                )
                for index, document in enumerate(documents)
            ),
            key=lambda item: (-item[1], item[0]),
        )
        return ranked[:top_n]

    def metrics(self) -> dict[str, int]:
        return {"physical_calls": self.calls, "logical_pairs": self.pairs}


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _generation(context: dict[str, Any], ordinal: int) -> dict[str, Any]:
    text = str(context["context"])
    digest = hashlib.sha256(text.encode()).hexdigest()
    result = ProviderResult(
        answer="UNKNOWN",
        answer_sha256=hashlib.sha256(b"UNKNOWN").hexdigest(),
        native_request_id=f"request-{ordinal:03d}",
        logical_request_id=f"logical-{ordinal:03d}",
        seed=1,
        cache_salt=digest,
        prompt_sha256=digest,
        prompt_tokens=512,
        no_memory_prompt_tokens=100,
        memory_tokens=min(int(context["context_tokens"]), TOKEN_BUDGET),
        completion_tokens=1,
        finish_reason="stop",
        context=text,
        context_truncated=False,
        tokenizer_calls=2,
        tokenize_latency_ms=0.1,
        provider_latency_ms=0.2,
    )
    return {
        "call_ordinal": ordinal,
        "case_id": context["case_id"],
        "method": context["method"],
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


def test_q8_builds_and_scores_six_fixed_control_arms_without_label_access() -> None:
    cases, _selection = load_public_dev_cases()
    plans = build_query_plans(cases)
    dense = _Dense()
    reranker = _Reranker()
    contexts, build_metrics = build_q8_contexts(
        cases,
        plans=plans,
        typed_context_archive=_json_object(DEFAULT_Q1R_CONTEXTS),
        dense=dense,
        reranker=reranker,
        token_count=lambda text: len(text.split()),
        index_text_projector=lambda text: " ".join(text.split()[:100]),
    )

    assert len(contexts) == 60
    assert {str(row["method"]) for row in contexts} == set(METHODS)
    assert contains_forbidden_label_key(contexts) is False
    assert dense.calls == 20
    assert reranker.calls == 20
    assert build_metrics["dense"]["metrics_delta"]["physical_calls"] == 20
    assert build_metrics["reranker"]["metrics_delta"]["physical_calls"] == 20
    assert build_metrics["index_projection"]["truncated_turn_count"] > 0
    assert build_metrics["index_projection"]["evidence_unit_content_changed"] is False
    for case in cases:
        rows = [row for row in contexts if row["case_id"] == case.case_id]
        assert len(rows) == 6
        assert len({str(row["query_plan_digest"]) for row in rows}) == 1
        assert len({str(row["memory_query_ir_digest"]) for row in rows}) == 1
        assert all(int(row["context_tokens"]) <= TOKEN_BUDGET for row in rows)
        for row in rows:
            if row["method"] in RETRIEVAL_METHODS:
                assert row["retrieval_trace"]["primitive_evidence_unit"] == "TURN"
            else:
                assert row["method"] == TYPED_REFERENCE
                assert row["method_role"].startswith("CROSS_MECHANISM")

    generations = [_generation(row, index) for index, row in enumerate(contexts)]
    _envelope, labeled_cases, labels = load_answer_bearing_labels()
    scoring_labels, _identity = load_public_dev_labels(
        tuple(str(case.case_id) for case in cases)
    )
    scored, summaries, decision = score_q8_generations(
        generations,
        contexts=contexts,
        cases=labeled_cases,
        answer_bearing_labels=labels,
        scoring_labels=scoring_labels,
    )

    assert len(scored) == 60
    assert set(summaries) == set(METHODS)
    assert summaries[TYPED_REFERENCE]["required_evidence_atom_denominator"] == 23
    assert summaries[TYPED_REFERENCE]["required_evidence_set_coverage"] == round(
        8 / 23, 9
    )
    assert "Q8_ACQUISITION_ONLY" in summaries[TYPED_REFERENCE][
        "coverage_identity_policy"
    ]
    assert decision["typed_reference_excluded_from_single_factor_attribution"] is True
    assert decision["production_default_frozen"] is False


def test_q8_condition_and_progress_are_fail_closed_before_labels(tmp_path: Path) -> None:
    condition = _validate_condition(_json_object(DEFAULT_Q0), _json_object(DEFAULT_Q6))
    assert condition["status"] == "SATISFIED"
    assert condition["q6_current_required_evidence_set_coverage"] == round(7 / 23, 9)

    generations = [{"case_id": "case-1", "method": "TURN_BM25"}]
    _write_progress(
        tmp_path,
        run_id="q8-test",
        planned_calls=60,
        generations=generations,
        failed_call={"ordinal": 1, "case_id": "case-1", "method": "STRONG_DENSE"},
    )
    progress = _json_object(tmp_path / "progress.json")
    assert progress["status"] == "FAILED_NOT_SCOREABLE"
    assert progress["labels_loaded"] is False
    assert progress["completed_call_count"] == 1

    _write_failure(
        tmp_path,
        run_id="q8-test",
        stage="READER_PROVIDER",
        completed_reader_calls=1,
        failed_call={"ordinal": 1},
        error=RuntimeError("synthetic failure"),
    )
    failure = _json_object(tmp_path / "failure-receipt.json")
    assert failure["status"] == "FAILED_NOT_SCOREABLE"
    assert failure["labels_loaded"] is False
    assert failure["automatic_retries"] == 0
