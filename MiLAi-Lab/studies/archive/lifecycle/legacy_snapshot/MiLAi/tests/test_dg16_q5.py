from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

import numpy as np

from evals.dg14.provider import ProviderResult
from evals.dg16.q5 import METHODS, run_q5_ablation


class _Dense:
    def __init__(self) -> None:
        self.identity: dict[str, Any] = {
            "model_id": "fake-dense",
            "dimensions": 3,
        }
        self.calls = 0

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        self.calls += 1
        rows = []
        for text in texts:
            lowered = text.casefold()
            vector = np.asarray(
                [
                    1.0 + lowered.count("coffee"),
                    1.0 + lowered.count("doctor"),
                    1.0 + lowered.count("project"),
                ],
                dtype=np.float32,
            )
            rows.append(vector / np.linalg.norm(vector))
        return np.stack(rows)

    def metrics(self) -> dict[str, int]:
        return {"physical_calls": self.calls}


class _Reranker:
    def __init__(self) -> None:
        self.identity: dict[str, Any] = {"model_id": "fake-reranker"}
        self.calls = 0

    def rerank(
        self, query: str, documents: Sequence[str], *, top_n: int
    ) -> list[tuple[int, float]]:
        del query
        self.calls += 1
        return [(index, float(top_n - index)) for index in range(top_n)]

    def metrics(self) -> dict[str, int]:
        return {"physical_calls": self.calls}


class _Provider:
    def answer(
        self,
        *,
        run_id: str,
        case_id: str,
        method_id: str,
        question: str,
        question_as_of: str,
        memory_context: str,
        token_budget: int,
    ) -> ProviderResult:
        del run_id, case_id, method_id, question, question_as_of
        digest = hashlib.sha256(memory_context.encode()).hexdigest()
        return ProviderResult(
            answer="UNKNOWN",
            answer_sha256=hashlib.sha256(b"UNKNOWN").hexdigest(),
            native_request_id=f"request-{digest[:12]}",
            logical_request_id=f"logical-{digest[:12]}",
            seed=1,
            cache_salt=digest,
            prompt_sha256=digest,
            prompt_tokens=token_budget,
            no_memory_prompt_tokens=100,
            memory_tokens=token_budget - 100,
            completion_tokens=1,
            finish_reason="stop",
            context=memory_context,
            context_truncated=False,
            tokenizer_calls=1,
            tokenize_latency_ms=0.1,
            provider_latency_ms=0.1,
        )


def test_q5_runs_a_fixed_four_arm_single_factor_matrix() -> None:
    dense = _Dense()
    reranker = _Reranker()

    receipt = run_q5_ablation(
        run_id="q5-test",
        dense=dense,
        reranker=reranker,
        provider=_Provider(),
        token_count=lambda text: len(text.split()),
        execution_identity={"hardware": "fake"},
    )

    assert receipt["status"] == "SUCCEEDED"
    assert receipt["case_count"] == 5
    assert receipt["cell_count"] == 20
    assert tuple(receipt["methods"]) == METHODS
    assert receipt["fixed_controls"]["evidence_unit"] == "CHUNK"
    assert receipt["fixed_controls"]["candidate_cap"] == 20
    assert receipt["fixed_controls"]["context_token_budget"] == 2_048
    assert dense.calls == 10
    assert reranker.calls == 10
    assert receipt["label_fields_available_to_product_path"] is False
    assert receipt["decision"]["production_default_frozen"] is False
