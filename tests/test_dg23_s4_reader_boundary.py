from __future__ import annotations

import hashlib
from pathlib import Path

from evals.dg14.provider import MatchedVllmProvider
from evals.dg23.reader_boundary import (
    DG23ReaderBoundary,
    DG23ReaderBoundaryError,
    ExactReaderIdentityRegistry,
)
from evals.dg23.reader_boundary_contract import (
    _SyntheticVllmPost,
    build_reader_boundary_contract_report,
)
from evals.dg23.reader_token_accounting import FrozenReaderTokenCounter

ROOT = Path(__file__).resolve().parents[1]


def test_dg23_s4_seed_and_exact_identity_are_budget_independent() -> None:
    report = build_reader_boundary_contract_report(ROOT)

    assert report["status"] == "PASS_EXACT_READER_IDENTITY_BOUNDARY"
    assert report["hard_gate"]["passed"]
    checks = report["hard_gate"]["checks"]
    assert checks["seed_excludes_arm_and_budget"]
    assert checks["exact_input_identity_equal"]
    assert checks["exact_identity_called_once"]


def test_dg23_s4_exact_token_overflow_and_infeasible_fail_before_reader() -> None:
    report = build_reader_boundary_contract_report(ROOT)
    checks = report["hard_gate"]["checks"]

    assert checks["overflow_fails_before_completion"]
    assert checks["overflow_send_time_truncation_zero"]
    assert checks["infeasible_reader_call_zero"]
    assert report["failure_injection"]["overflow_completion_calls"] == 0


def test_dg23_s4_invalid_json_is_not_repaired_or_retried() -> None:
    report = build_reader_boundary_contract_report(ROOT)

    assert report["hard_gate"]["checks"]["invalid_json_fail_closed_no_retry"]
    assert report["failure_injection"]["invalid_json_completion_calls"] == 1
    assert report["execution_counts"]["opened_dev_reader_calls"] == 0
    assert report["execution_counts"]["external_provider_calls"] == 0


def test_dg23_s4_local_preflight_counts_the_frozen_chat_envelope() -> None:
    counter = FrozenReaderTokenCounter()
    context = (
        "MILAI_MEMORY_DATA_BEGIN\n\n"
        "[MEMORY DECISION STATUS]\n"
        "memory_status=HIT\n"
        "sufficiency_status=COMPLETE\n\n"
        "[E1 EVIDENCE WINDOW / NON-CANONICAL]\n"
        "USER: The kitchen purchase code is 47.\n\n"
        "MILAI_MEMORY_DATA_END"
    )

    observed = counter.memory_tokens(
        question="What is the kitchen purchase code?",
        question_as_of="2026-08-29T09:00:00+08:00",
        memory_context=context,
    )

    assert observed > 0
    assert observed != len(counter._tokenizer.encode(context).ids)


def test_dg23_s4_boundary_overflow_fails_before_provider_tokenize_or_completion() -> None:
    post = _SyntheticVllmPost()
    boundary = DG23ReaderBoundary(MatchedVllmProvider(post_json=post))
    context = "oversized exact memory " * 100

    try:
        boundary.read(
            run_id="dg23-s4-local-preflight",
            case_id="synthetic-local-overflow",
            method_id="EXACT",
            presentation_budget=1,
            source_snapshot_digest="b" * 64,
            replicate_index=0,
            question="What is recorded?",
            question_as_of="2026-08-29T09:00:00+08:00",
            memory_context=context,
            reader_context_digest=hashlib.sha256(context.encode()).hexdigest(),
            estimated_tokens=500,
        )
    except DG23ReaderBoundaryError as exc:
        assert exc.reason_code == "TOKEN_ACCOUNTING_MISMATCH"
        assert exc.metadata["completion_call_attempted"] is False
    else:
        raise AssertionError("Reader boundary must fail closed on local overflow")

    assert post.tokenizer_calls == 0
    assert post.completion_calls == 0


def test_dg23_s4_restored_identity_is_claimed_once_without_a_new_call() -> None:
    source_snapshot = "c" * 64
    context = "MILAI_MEMORY_DATA_BEGIN\nvalue=47\nMILAI_MEMORY_DATA_END"
    digest = hashlib.sha256(context.encode()).hexdigest()
    first_post = _SyntheticVllmPost()
    first = DG23ReaderBoundary(MatchedVllmProvider(post_json=first_post)).read(
        run_id="dg23-s4-before-interruption",
        case_id="synthetic-restore",
        method_id="ARM_A",
        presentation_budget=512,
        source_snapshot_digest=source_snapshot,
        replicate_index=0,
        question="What is the value?",
        question_as_of="2026-08-29T09:00:00+08:00",
        memory_context=context,
        reader_context_digest=digest,
        estimated_tokens=32,
    )
    registry = ExactReaderIdentityRegistry()
    registry.restore(first)
    resumed_post = _SyntheticVllmPost()
    resumed_boundary = DG23ReaderBoundary(
        MatchedVllmProvider(post_json=resumed_post), registry=registry
    )

    restored = resumed_boundary.read(
        run_id="dg23-s4-after-interruption",
        case_id="synthetic-restore",
        method_id="ARM_A",
        presentation_budget=512,
        source_snapshot_digest=source_snapshot,
        replicate_index=0,
        question="What is the value?",
        question_as_of="2026-08-29T09:00:00+08:00",
        memory_context=context,
        reader_context_digest=digest,
        estimated_tokens=32,
    )
    reused = resumed_boundary.read(
        run_id="dg23-s4-after-interruption",
        case_id="synthetic-restore",
        method_id="ARM_B",
        presentation_budget=2048,
        source_snapshot_digest=source_snapshot,
        replicate_index=0,
        question="What is the value?",
        question_as_of="2026-08-29T09:00:00+08:00",
        memory_context=context,
        reader_context_digest=digest,
        estimated_tokens=32,
    )

    assert restored.disposition == "RESTORED_PROVIDER_RESULT"
    assert reused.disposition == "EXACT_IDENTITY_REUSE"
    assert registry.provider_calls == 1
    assert registry.restored_provider_calls == 1
    assert registry.fresh_provider_calls == 0
    assert registry.exact_identity_reuses == 1
    assert resumed_post.tokenizer_calls == 0
    assert resumed_post.completion_calls == 0
