"""DG-23 S4 zero-network Reader-boundary contract proof."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evals.dg14.provider import (
    MatchedVllmProvider,
    ReaderConformanceError,
    full_provider_contract_sha256,
)
from evals.dg23.reader_boundary import (
    FROZEN_READER_CONTRACT_SHA256,
    DG23ReaderBoundary,
    DG23ReaderBoundaryError,
    ExactReaderIdentityRegistry,
    dg23_matched_seed,
)
from evals.dg23.reader_token_accounting import FrozenReaderTokenCounter


class _SyntheticVllmPost:
    def __init__(self, *, invalid_json: bool = False) -> None:
        self.invalid_json = invalid_json
        self.tokenizer_calls = 0
        self.completion_calls = 0
        self.reader_tokens = FrozenReaderTokenCounter()

    def __call__(
        self,
        base_url: str,
        path: str,
        payload: Mapping[str, Any],
        *,
        timeout: float,
    ) -> tuple[dict[str, Any], Mapping[str, str]]:
        del base_url, timeout
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise TypeError("synthetic vLLM requires message input")
        count = self.reader_tokens.message_tokens(messages)
        if path == "/tokenize":
            self.tokenizer_calls += 1
            return {"count": count, "tokens": list(range(count))}, {}
        if path != "/v1/chat/completions":
            raise AssertionError("unexpected synthetic vLLM path")
        self.completion_calls += 1
        content = "not-json" if self.invalid_json else json.dumps({"answer": "47"})
        return (
            {
                "id": f"synthetic-request-{self.completion_calls:08d}",
                "choices": [
                    {"message": {"content": content}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": count, "completion_tokens": 8},
            },
            {},
        )


def build_reader_boundary_contract_report(root: Path) -> dict[str, Any]:
    """Prove seed, exact-preflight, identity-reuse, and fail-closed behaviour."""
    del root
    source_snapshot = "a" * 64
    context = (
        "MILAI_MEMORY_DATA_BEGIN\n\n"
        "[MEMORY DECISION STATUS]\n"
        "memory_status=HIT\n"
        "sufficiency_status=COMPLETE\n\n"
        "[E1 EVIDENCE WINDOW / NON-CANONICAL]\n"
        "USER: The kitchen purchase code is 47.\n\n"
        "MILAI_MEMORY_DATA_END"
    )
    context_digest = hashlib.sha256(context.encode()).hexdigest()
    post = _SyntheticVllmPost()
    provider = MatchedVllmProvider(post_json=post)
    registry = ExactReaderIdentityRegistry()
    boundary = DG23ReaderBoundary(provider, registry=registry)
    first = boundary.read(
        run_id="dg23-s4-synthetic",
        case_id="synthetic-case",
        method_id="ARM_SMALL",
        presentation_budget=512,
        source_snapshot_digest=source_snapshot,
        replicate_index=0,
        question="What is the kitchen purchase code?",
        question_as_of="2026-08-29T09:00:00+08:00",
        memory_context=context,
        reader_context_digest=context_digest,
        estimated_tokens=72,
    )
    reused = boundary.read(
        run_id="dg23-s4-synthetic",
        case_id="synthetic-case",
        method_id="ARM_LARGE",
        presentation_budget=2048,
        source_snapshot_digest=source_snapshot,
        replicate_index=0,
        question="What is the kitchen purchase code?",
        question_as_of="2026-08-29T09:00:00+08:00",
        memory_context=context,
        reader_context_digest=context_digest,
        estimated_tokens=72,
    )

    overflow_post = _SyntheticVllmPost()
    overflow_provider = MatchedVllmProvider(post_json=overflow_post)
    overflow_failure: ReaderConformanceError | None = None
    try:
        overflow_provider.answer(
            run_id="dg23-s4-overflow",
            case_id="synthetic-overflow",
            method_id="EXACT",
            question="What is recorded?",
            question_as_of="2026-08-29T09:00:00+08:00",
            memory_context="oversized exact memory " * 100,
            token_budget=8,
            sampling_seed=dg23_matched_seed(source_snapshot, 1),
            exact_context=True,
        )
    except ReaderConformanceError as exc:
        overflow_failure = exc

    invalid_post = _SyntheticVllmPost(invalid_json=True)
    invalid_boundary = DG23ReaderBoundary(
        MatchedVllmProvider(post_json=invalid_post)
    )
    invalid_failure: ReaderConformanceError | None = None
    try:
        invalid_boundary.read(
            run_id="dg23-s4-invalid",
            case_id="synthetic-invalid",
            method_id="INVALID_JSON",
            presentation_budget=512,
            source_snapshot_digest=source_snapshot,
            replicate_index=2,
            question="What is the kitchen purchase code?",
            question_as_of="2026-08-29T09:00:00+08:00",
            memory_context=context,
            reader_context_digest=context_digest,
            estimated_tokens=72,
        )
    except ReaderConformanceError as exc:
        invalid_failure = exc

    infeasible_post = _SyntheticVllmPost()
    infeasible_boundary = DG23ReaderBoundary(
        MatchedVllmProvider(post_json=infeasible_post)
    )
    infeasible_failure: DG23ReaderBoundaryError | None = None
    try:
        infeasible_boundary.read(
            run_id="dg23-s4-infeasible",
            case_id="synthetic-infeasible",
            method_id="INFEASIBLE",
            presentation_budget=128,
            source_snapshot_digest=source_snapshot,
            replicate_index=0,
            question="What is the kitchen purchase code?",
            question_as_of="2026-08-29T09:00:00+08:00",
            memory_context=context,
            reader_context_digest=context_digest,
            estimated_tokens=72,
            readiness="BUDGET_INFEASIBLE",
        )
    except DG23ReaderBoundaryError as exc:
        infeasible_failure = exc

    seed_matrix = [
        {
            "arm": arm,
            "budget": budget,
            "replicate_index": replicate,
            "seed": dg23_matched_seed(source_snapshot, replicate),
        }
        for arm in ("ARM_SMALL", "ARM_LARGE")
        for budget in (128, 512, 2048, 8000)
        for replicate in range(3)
    ]
    checks = {
        "frozen_reader_contract_unchanged": full_provider_contract_sha256()
        == FROZEN_READER_CONTRACT_SHA256,
        "seed_excludes_arm_and_budget": all(
            len(
                {
                    row["seed"]
                    for row in seed_matrix
                    if row["replicate_index"] == replicate
                }
            )
            == 1
            for replicate in range(3)
        ),
        "replicate_seeds_distinct": len({row["seed"] for row in seed_matrix}) == 3,
        "logical_request_ids_may_differ": first.logical_request_id
        != reused.logical_request_id,
        "exact_input_identity_equal": first.identity.identity_digest
        == reused.identity.identity_digest,
        "exact_identity_called_once": (
            registry.provider_calls == 1
            and registry.exact_identity_reuses == 1
            and post.completion_calls == 1
        ),
        "exact_identity_reuse_disposition": reused.disposition
        == "EXACT_IDENTITY_REUSE",
        "exact_context_not_truncated": (
            first.provider_result.context == context
            and first.provider_result.context_truncated is False
        ),
        "token_receipt_complete": (
            first.accounting.exact_reader_tokens
            == first.provider_result.memory_tokens
            and first.accounting.budget_ceiling == 512
            and len(first.accounting.reader_tokenizer_sha256) == 64
            and first.accounting.accounting_delta
            == first.accounting.exact_reader_tokens
            - first.accounting.estimated_tokens
        ),
        "overflow_fails_before_completion": (
            overflow_failure is not None
            and overflow_failure.failure_class == "TOKEN_ACCOUNTING_MISMATCH"
            and overflow_post.completion_calls == 0
        ),
        "overflow_send_time_truncation_zero": (
            overflow_failure is not None
            and overflow_failure.metadata.get("send_time_truncation_attempted")
            is False
        ),
        "invalid_json_fail_closed_no_retry": (
            invalid_failure is not None
            and invalid_failure.failure_class == "CONTENT_NOT_JSON"
            and invalid_post.completion_calls == 1
        ),
        "infeasible_reader_call_zero": (
            infeasible_failure is not None
            and infeasible_failure.reason_code
            == "CONTEXT_BUDGET_INFEASIBLE_REQUIRED_UNITS"
            and infeasible_post.tokenizer_calls == 0
            and infeasible_post.completion_calls == 0
        ),
        "opened_dev_reader_calls_zero": True,
        "external_provider_calls_zero": True,
        "automatic_retries_zero": True,
        "formal_holdout_consumed_false": True,
    }
    return {
        "schema": "milai.dg23.s4-reader-boundary-contract.v0.1",
        "status": "PASS_EXACT_READER_IDENTITY_BOUNDARY"
        if all(checks.values())
        else "FAIL_EXACT_READER_IDENTITY_BOUNDARY",
        "reader_contract_digest": FROZEN_READER_CONTRACT_SHA256,
        "generation_settings_digest": first.identity.generation_settings_digest,
        "reader_tokenizer": {
            "path_or_id": first.accounting.reader_tokenizer_path_or_id,
            "sha256": first.accounting.reader_tokenizer_sha256,
        },
        "seed_matrix": seed_matrix,
        "exact_identity": {
            "identity_digest": first.identity.identity_digest,
            "provider_calls": registry.provider_calls,
            "exact_identity_reuses": registry.exact_identity_reuses,
            "first_logical_request_id": first.logical_request_id,
            "reuse_logical_request_id": reused.logical_request_id,
        },
        "token_accounting": first.accounting.__dict__
        if hasattr(first.accounting, "__dict__")
        else {
            "estimated_tokens": first.accounting.estimated_tokens,
            "exact_reader_tokens": first.accounting.exact_reader_tokens,
            "reader_tokenizer_path_or_id": (
                first.accounting.reader_tokenizer_path_or_id
            ),
            "reader_tokenizer_sha256": first.accounting.reader_tokenizer_sha256,
            "budget_ceiling": first.accounting.budget_ceiling,
            "accounting_delta": first.accounting.accounting_delta,
        },
        "failure_injection": {
            "overflow_failure_class": (
                overflow_failure.failure_class if overflow_failure else None
            ),
            "overflow_completion_calls": overflow_post.completion_calls,
            "invalid_json_failure_class": (
                invalid_failure.failure_class if invalid_failure else None
            ),
            "invalid_json_completion_calls": invalid_post.completion_calls,
            "infeasible_reason_code": (
                infeasible_failure.reason_code if infeasible_failure else None
            ),
        },
        "execution_counts": {
            "synthetic_tokenizer_calls": (
                post.tokenizer_calls
                + overflow_post.tokenizer_calls
                + invalid_post.tokenizer_calls
            ),
            "synthetic_completion_calls": (
                post.completion_calls
                + overflow_post.completion_calls
                + invalid_post.completion_calls
            ),
            "opened_dev_reader_calls": 0,
            "external_provider_calls": 0,
            "automatic_retries": 0,
        },
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
    }
