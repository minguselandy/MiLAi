from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from evals.dg14.provider import (
    full_provider_contract_sha256,
    logical_request_id,
    matched_seed,
)
from evals.dg21.matched_eval import PRODUCT_SCHEMA
from evals.paper.provider import MODEL_ID
from scripts.run_dg21_s7_matched import (
    READER_PROGRESS_SCHEMA,
    SEED_RUN_ID,
    DG21S7RunError,
    _reader_failure_record,
    _reader_progress_product,
    _sealed_reader_reuse_index,
)


def _product(
    *, answer: str = "bounded answer", seed_delta: int = 0
) -> dict[str, object]:
    case_id = "synthetic-case"
    budget = 512
    arm = "D_SAFE_QUERY_TIME_TEMPORAL_EVENT"
    context = "sealed governed context"
    context_digest = hashlib.sha256(context.encode()).hexdigest()
    return {
        "schema": PRODUCT_SCHEMA,
        "labels_loaded": False,
        "formal_holdout_consumed": False,
        "reader_model_id": MODEL_ID,
        "provider_contract_sha256": full_provider_contract_sha256(),
        "records": [
            {
                "case_id": case_id,
                "token_budget": budget,
                "arm": arm,
                "reader_source": "FROZEN_READER_AFTER_CONTEXT_SEAL",
                "context": context,
                "context_sha256": context_digest,
                "answer": answer,
                "provider": {
                    "answer": answer,
                    "context_sha256": context_digest,
                    "context_truncated": False,
                    "finish_reason": "stop",
                    "provider_calls": 1,
                    "seed": matched_seed(SEED_RUN_ID, case_id, budget) + seed_delta,
                    "logical_request_id": logical_request_id(
                        SEED_RUN_ID, case_id, arm, budget
                    ),
                },
            }
        ],
    }


def test_sealed_reader_reuse_is_content_and_identity_addressed(tmp_path: Path) -> None:
    product = _product()
    index = _sealed_reader_reuse_index([(tmp_path / "sealed-product.json", product)])

    row = product["records"][0]  # type: ignore[index]
    key = (
        row["case_id"],
        row["token_budget"],
        row["arm"],
        row["context_sha256"],
    )
    assert index[key]["answer"] == "bounded answer"


def test_sealed_reader_reuse_rejects_seed_drift(tmp_path: Path) -> None:
    with pytest.raises(DG21S7RunError, match="record identity"):
        _sealed_reader_reuse_index(
            [(tmp_path / "seed-drift.json", _product(seed_delta=1))]
        )


def test_sealed_reader_reuse_rejects_conflicting_answers(tmp_path: Path) -> None:
    with pytest.raises(DG21S7RunError, match="Conflicting"):
        _sealed_reader_reuse_index(
            [
                (tmp_path / "first.json", _product(answer="first")),
                (tmp_path / "second.json", _product(answer="second")),
            ]
        )


def test_reader_failure_record_is_identity_complete_and_text_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("scripts.run_dg21_s7_matched.ROOT", tmp_path)
    context_path = tmp_path / "sealed-context.json"
    context_path.write_text("{}\n", encoding="utf-8")
    row = {
        "case_id": "synthetic-case",
        "arm": "D_SAFE_QUERY_TIME_TEMPORAL_EVENT",
        "token_budget": 512,
        "context_sha256": "context-digest",
        "semantic_context_digest": "semantic-digest",
        "reader_context_digest": "reader-digest",
        "context": "must not be copied",
    }

    record = _reader_failure_record(
        run_id="failed-run",
        row=row,
        reader_attempt_ordinal=3,
        context_path=context_path,
        exc=ValueError("strict result invalid"),
    )

    assert record["reader_attempt_ordinal"] == 3
    assert record["context_sha256"] == "context-digest"
    assert record["logical_request_id"] == logical_request_id(
        SEED_RUN_ID,
        "synthetic-case",
        "D_SAFE_QUERY_TIME_TEMPORAL_EVENT",
        512,
    )
    assert record["seed"] == matched_seed(SEED_RUN_ID, "synthetic-case", 512)
    assert record["question_context_answer_or_labels_persisted"] is False
    assert "context" not in record
    assert "answer" not in record


def test_reader_progress_is_unscored_and_reusable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("scripts.run_dg21_s7_matched.ROOT", tmp_path)
    context_path = tmp_path / "sealed-context.json"
    context_path.write_text("{}\n", encoding="utf-8")
    product = _product()
    progress = _reader_progress_product(
        run_id="interrupted-run",
        context_path=context_path,
        records=product["records"],  # type: ignore[arg-type]
    )

    assert progress["schema"] == READER_PROGRESS_SCHEMA
    assert progress["status"] == "READER_PROGRESS_UNSCORED"
    assert progress["labels_loaded"] is False
    assert progress["automatic_retries"] == 0
    index = _sealed_reader_reuse_index([(tmp_path / "progress.json", progress)])
    row = product["records"][0]  # type: ignore[index]
    key = (
        row["case_id"],
        row["token_budget"],
        row["arm"],
        row["context_sha256"],
    )
    assert index[key]["answer"] == "bounded answer"
