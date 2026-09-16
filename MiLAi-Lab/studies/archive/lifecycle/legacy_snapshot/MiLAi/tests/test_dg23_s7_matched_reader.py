from __future__ import annotations

import hashlib
from pathlib import Path

from evals.dg14.provider import MatchedVllmProvider
from evals.dg23.matched_reader import (
    ARMS,
    BASELINE_ARM,
    CANDIDATE_ARM,
    MODES,
    REPLICATES,
    build_matched_reader_context_product,
    seal_matched_reader_context_product,
)
from evals.dg23.reader_boundary import DG23ReaderBoundary, ExactReaderIdentityRegistry
from evals.dg23.reader_boundary_contract import _SyntheticVllmPost
from scripts.run_dg23_s7_matched_reader import _restore_reader_progress

ROOT = Path(__file__).resolve().parents[1]


def test_dg23_s7_context_product_is_label_free_and_has_frozen_denominator(
    tmp_path: Path,
) -> None:
    product = build_matched_reader_context_product(ROOT, run_id="dg23-s7-contract-test")

    assert product["labels_loaded"] is False
    assert product["answers_present"] is False
    assert product["formal_holdout_consumed"] is False
    assert product["candidate_default"] is False
    assert product["arms"] == list(ARMS)
    assert product["modes"] == list(MODES)
    assert product["replicates"] == list(REPLICATES)
    assert len(product["records"]) == 240
    assert all("answer" not in row for row in product["records"])

    path = tmp_path / "sealed-contexts.json"
    seal_matched_reader_context_product(product, path)
    assert path.is_file()


def test_dg23_s7_seed_is_arm_and_mode_independent_and_contexts_are_exact() -> None:
    product = build_matched_reader_context_product(ROOT, run_id="dg23-s7-identity-test")
    records = product["records"]
    for case_id in product["case_order"]:
        for replicate in REPLICATES:
            cells = [
                row
                for row in records
                if row["case_id"] == case_id and row["replicate_index"] == replicate
            ]
            assert len(cells) == len(ARMS) * len(MODES)
            assert len({row["sampling_seed"] for row in cells}) == 1
    assert all(
        hashlib.sha256(row["context"].encode()).hexdigest()
        == row["reader_context_digest"]
        for row in records
    )
    assert all(
        row["source_mode"] == "DG22_FROZEN_512"
        for row in records
        if row["arm"] == BASELINE_ARM and row["mode"] == "LEGACY_512"
    )
    assert all(
        row["source_mode"] == "DG22_FROZEN_2048"
        for row in records
        if row["arm"] == BASELINE_ARM and row["mode"] != "LEGACY_512"
    )
    assert any(
        row["readiness"] == "BUDGET_INFEASIBLE"
        for row in records
        if row["arm"] == CANDIDATE_ARM and row["mode"] == "LEGACY_512"
    )


def test_dg23_s7_restores_interrupted_exact_identities_without_reissuing_calls() -> None:
    product = build_matched_reader_context_product(ROOT, run_id="dg23-s7-resume-test")
    registry = ExactReaderIdentityRegistry()
    post = _SyntheticVllmPost()
    boundary = DG23ReaderBoundary(
        MatchedVllmProvider(post_json=post),
        registry=registry,
    )
    progress = ROOT / (
        "var/dg23/s7/dg23-s7-matched-reader-20260829-001/reader-progress.json"
    )

    receipt = _restore_reader_progress(
        progress,
        context_product=product,
        boundary=boundary,
        registry=registry,
    )

    assert receipt["status"] == "RESTORED_EXACT_IDENTITIES"
    assert receipt["restored_provider_calls"] == 3
    assert registry.provider_calls == 3
    assert registry.fresh_provider_calls == 0
    assert post.tokenizer_calls == 0
    assert post.completion_calls == 0

    first = product["records"][0]
    result = boundary.read(
        run_id="dg23-s7-resume-test",
        case_id=str(first["case_id"]),
        method_id=str(first["method_id"]),
        presentation_budget=int(first["presentation_budget"]),
        source_snapshot_digest=str(first["source_snapshot_digest"]),
        replicate_index=int(first["replicate_index"]),
        question=str(first["question"]),
        question_as_of=str(first["question_as_of"]),
        memory_context=str(first["context"]),
        reader_context_digest=str(first["reader_context_digest"]),
        estimated_tokens=int(first["estimated_tokens"]),
    )

    assert result.disposition == "RESTORED_PROVIDER_RESULT"
    assert registry.exact_identity_reuses == 0
    assert post.completion_calls == 0
