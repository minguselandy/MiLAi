from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

import numpy as np
from milai.adapters import DeterministicHashEmbedding, ProjectionIdentity

from evals.dg16.lme10 import load_public_dev_cases
from evals.dg17.a6_dense_productization import (
    build_a6_label_free_archive,
    contains_forbidden_label_key,
    estimate_a6_work,
    score_a6_archive,
)
from evals.dg17.measurement import load_answer_bearing_labels


class _FakeDense:
    identity: ClassVar[dict[str, Any]] = {
        "provider": "deterministic_fixture",
        "model_id": "deterministic-hash-v1",
        "source_dimensions": 16,
    }

    def __init__(self) -> None:
        self._provider = DeterministicHashEmbedding()
        self._calls = 0
        self._items = 0

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        self._calls += 1
        self._items += len(texts)
        vectors = []
        for text in texts:
            vector = self._provider.embed(text)
            if not any(vector):
                vector[0] = 1.0
            vectors.append(vector)
        return np.asarray(vectors, dtype=np.float32)

    def metrics(self) -> Mapping[str, Any]:
        return {
            "physical_calls": self._calls,
            "logical_items": self._items,
            "latency_ms": 0.0,
        }


def test_a6_archive_is_label_free_single_factor_and_scoreable() -> None:
    cases, _selection = load_public_dev_cases()
    work = estimate_a6_work(cases)
    identity = ProjectionIdentity(
        provider="deterministic_fixture",
        model_id="deterministic-hash-v1",
        source_dimensions=16,
        projection_dimensions=128,
        normalization="source-l2+signed-projection-l2",
        code_version="projection-128/v1",
    )

    archive = build_a6_label_free_archive(
        cases,
        dense=_FakeDense(),
        projection_identity=identity,
        run_id="test-a6",
    )

    assert work["case_count"] == 10
    assert 0 < work["evidence_turn_count"] <= 4933
    assert work["executed_dense_probe_count"] > 0
    assert archive["record_count"] == 20
    assert archive["labels_loaded"] is False
    assert archive["label_fields_available_to_product_path"] is False
    assert archive["efficiency"]["reranker_calls"] == 0
    assert archive["projection"]["full_turn_source_mutated"] is False
    assert contains_forbidden_label_key(archive) is False
    by_case: dict[str, list[Mapping[str, Any]]] = {}
    for record in archive["records"]:
        by_case.setdefault(record["case_id"], []).append(record)
    assert all(len(records) == 2 for records in by_case.values())
    assert all(
        len({record["corpus_digest"] for record in records}) == 1
        for records in by_case.values()
    )
    assert hashlib.sha256(str(archive["records"]).encode()).hexdigest()

    _envelope, labeled_cases, labels = load_answer_bearing_labels()
    assert tuple(case.case_id for case in labeled_cases) == tuple(
        case.case_id for case in cases
    )
    score = score_a6_archive(archive, labels=labels)
    assert score["arms"]["FTS_RAW"]["answer_bearing_atom_denominator"] == 23
    assert score["arms"]["FTS_RAW_PLUS_EVIDENCE_DENSE_128"][
        "answer_bearing_source_turn_denominator"
    ] == 21
    assert score["aggregate_gate_diagnostic"]["scope"].startswith("A1_THROUGH_A7")
