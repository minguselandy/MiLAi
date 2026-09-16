from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from evals.dg16.lme10 import load_public_dev_cases
from evals.dg17.acquisition_loss import (
    PATHS,
    attribute_acquisition_losses,
    build_label_free_trace,
)
from evals.dg17.measurement import load_answer_bearing_labels
from evals.dg17.q8_retrieval_ablation import (
    build_query_plans,
    contains_forbidden_label_key,
)
from scripts.run_dg17_q8_retrieval_ablation import DEFAULT_Q6


class _Dense:
    def __init__(self) -> None:
        self.identity: dict[str, Any] = {"model_id": "fake-dense"}
        self.calls = 0
        self.items = 0

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        self.calls += 1
        self.items += len(texts)
        rows: list[np.ndarray[Any, Any]] = []
        for value in texts:
            lowered = value.casefold()
            vector = np.asarray(
                [
                    1.0 + len(lowered) % 31,
                    1.0 + lowered.count("event"),
                    1.0 + lowered.count("friend"),
                    1.0 + lowered.count("day"),
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
        terms = set(query.casefold().split())
        return sorted(
            (
                (
                    index,
                    float(len(terms.intersection(document.casefold().split()))),
                )
                for index, document in enumerate(documents)
            ),
            key=lambda item: (-item[1], item[0]),
        )[:top_n]

    def metrics(self) -> dict[str, int]:
        return {"physical_calls": self.calls, "logical_pairs": self.pairs}


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_a0_seals_label_free_trace_then_attributes_all_23_evidence_items() -> None:
    cases, _selection = load_public_dev_cases()
    plans = build_query_plans(cases)
    dense = _Dense()
    reranker = _Reranker()

    trace, metrics = build_label_free_trace(
        cases,
        plans=plans,
        q6_receipt=_object(DEFAULT_Q6),
        dense=dense,
        reranker=reranker,
        token_count=lambda value: len(value.split()),
        index_text_projector=lambda value: " ".join(value.split()[:200]),
    )

    assert trace["labels_loaded"] is False
    assert trace["product_path_label_access_count"] == 0
    assert trace["reader_calls"] == 0
    assert contains_forbidden_label_key(trace) is False
    assert len(trace["cases"]) == 10
    assert dense.calls == 20
    assert reranker.calls == 20
    assert metrics["q8_replay_identity_equal"] is None

    _envelope, labeled_cases, labels = load_answer_bearing_labels()
    assert tuple(case.case_id for case in labeled_cases) == tuple(
        case.case_id for case in cases
    )
    records, summary = attribute_acquisition_losses(trace, labels=labels)

    assert len(records) == 23 * len(PATHS)
    assert summary["unique_case_count"] == 10
    assert summary["unique_required_evidence_count"] == 23
    assert summary["gold_label_product_path_access_count"] == 0
    assert summary["all_records_have_exactly_one_first_loss"] is True
    assert set(summary["paths"]) == set(PATHS)
    assert all(
        path_summary["required_evidence_denominator"] == 23
        for path_summary in summary["paths"].values()
    )
    assert all(record["first_loss_stage"] for record in records)
