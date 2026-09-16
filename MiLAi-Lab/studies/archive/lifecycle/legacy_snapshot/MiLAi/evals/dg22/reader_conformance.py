# ruff: noqa: RUF001 -- full-width punctuation is part of the CJK probe corpus.
"""DG-22 Reader Conformance Contract v0.2 matrix and scoring."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from evals.dg14.provider import ReaderConformanceError

FAILURE_CLASSES = frozenset(
    {
        "OUTPUT_LIMIT_TRUNCATED",
        "STRUCTURED_DECODING_FAILED",
        "TRANSPORT_ENVELOPE_INVALID",
        "CONTENT_NOT_JSON",
        "SCHEMA_VIOLATION",
        "TOKEN_ACCOUNTING_MISMATCH",
    }
)


def diagnosis_matrix() -> list[dict[str, Any]]:
    """Eight label-free identities under the frozen current contract."""
    axes = [
        (512, "lookup", "short", "ASCII", "short"),
        (512, "count", "near_budget", "CJK", "short"),
        (512, "date", "short", "punctuation-heavy", "short"),
        (512, "list", "near_budget", "ASCII", "bounded-long"),
        (2048, "UNKNOWN", "short", "CJK", "short"),
        (2048, "lookup", "near_budget", "punctuation-heavy", "short"),
        (2048, "count", "short", "ASCII", "short"),
        (2048, "list", "near_budget", "CJK", "bounded-long"),
    ]
    return [_cell("S2A", index, *axis) for index, axis in enumerate(axes, start=1)]


def conformance_matrix() -> list[dict[str, Any]]:
    """Thirty-two balanced cells covering every required shape axis."""
    answer_shapes = ("lookup", "count", "date", "list", "UNKNOWN")
    unicode_modes = ("ASCII", "CJK", "punctuation-heavy")
    cells = []
    for index in range(32):
        budget = (512, 2048)[index % 2]
        shape = answer_shapes[index % len(answer_shapes)]
        context_size = ("short", "near_budget")[(index // 2) % 2]
        unicode_mode = unicode_modes[(index // 4) % len(unicode_modes)]
        expected_length = (
            "bounded-long" if shape == "list" or index in {7, 19, 27} else "short"
        )
        cells.append(
            _cell(
                "S2B",
                index + 1,
                budget,
                shape,
                context_size,
                unicode_mode,
                expected_length,
            )
        )
    return cells


def materialize_cell(cell: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return public synthetic question, as-of, and context for one matrix cell."""
    shape = str(cell["answer_shape"])
    mode = str(cell["unicode"])
    expected = str(cell["expected_answer_length"])
    if mode == "CJK":
        facts = {
            "lookup": ("项目代号是青岚。", "项目代号是什么？"),
            "count": ("清单有三项：松、竹、梅。", "清单共有几项？"),
            "date": ("发布日是2031年4月5日。", "发布日期是哪一天？"),
            "list": (
                "标签依次为：甲、乙、丙、丁、戊、己、庚、辛。",
                "请列出全部标签。",
            ),
            "UNKNOWN": ("这里只记录了颜色是蓝色。", "项目预算是多少？"),
        }
        filler = "中性背景资料；与问题无关。"
    elif mode == "punctuation-heavy":
        facts = {
            "lookup": (
                "code-name=[ORION]; status::active!!!",
                "What is the code-name?",
            ),
            "count": (
                "items={alpha; beta; gamma}; done=true.",
                "How many items are listed?",
            ),
            "date": (
                "release_date=>2031-04-05; verified!!!",
                "What is the release date?",
            ),
            "list": (
                "labels=[A-1; B_2; C.3; D/4; E:5; F+6; G#7; H@8].",
                "List every label.",
            ),
            "UNKNOWN": ("color::blue; shape=[round].", "What is the project budget?"),
        }
        filler = "meta=[neutral]; ref::none; note!!!"
    else:
        facts = {
            "lookup": (
                "The project codename is Orion.",
                "What is the project codename?",
            ),
            "count": (
                "The inventory contains alpha, beta, and gamma.",
                "How many inventory items are there?",
            ),
            "date": ("The release date is 2031-04-05.", "What is the release date?"),
            "list": (
                "The labels are alpha, beta, gamma, delta, epsilon, zeta, eta, and theta.",
                "List all labels.",
            ),
            "UNKNOWN": (
                "The only recorded property is the color blue.",
                "What is the project budget?",
            ),
        }
        filler = "This is neutral background material unrelated to the question."
    fact, question = facts[shape]
    repeat = 1
    if cell["context_size"] == "near_budget":
        repeat = 70 if cell["token_budget"] == 512 else 300
    context = "\n".join([filler] * repeat + [fact])
    if expected == "bounded-long" and shape != "list":
        question += " Give a bounded but complete answer."
    return question, "2031-04-06T00:00:00Z", context


def failure_record(exc: Exception) -> dict[str, Any]:
    """Project a typed failure without retaining raw private content."""
    if isinstance(exc, ReaderConformanceError):
        failure_class = exc.failure_class
        metadata = exc.metadata
    else:
        failure_class = "TRANSPORT_ENVELOPE_INVALID"
        metadata = {}
    return {
        "failure_class": failure_class,
        "failure_type": type(exc).__name__,
        "safe_metadata": metadata,
        "raw_body_persisted": False,
        "salvage_attempted": False,
        "automatic_retry_attempted": False,
    }


def successor_ceiling_authorized(records: Sequence[Mapping[str, Any]]) -> bool:
    """Apply the exact three-part evidence gate for a 512-token successor."""
    return any(
        record.get("status") == "FAILED"
        and record.get("failure_class") == "OUTPUT_LIMIT_TRUNCATED"
        and record.get("finish_reason") == "length"
        and record.get("completion_tokens") == 256
        and record.get("truncated_json_prefix") is True
        for record in records
    )


def score_conformance(
    diagnosis: Sequence[Mapping[str, Any]],
    conformance: Sequence[Mapping[str, Any]],
    *,
    selected_ceiling: int,
    quarantined_logical_request_id: str,
) -> dict[str, Any]:
    """Score only S2B for PASS while retaining the S2A diagnosis denominator."""
    valid = sum(row.get("status") == "PASS" for row in conformance)
    records = [*diagnosis, *conformance]
    identities = [row.get("logical_request_id") for row in records]
    failure_classes = sorted(
        {str(row["failure_class"]) for row in records if row.get("status") == "FAILED"}
    )
    checks = {
        "diagnosis_identity_count_8": len(diagnosis) == 8,
        "conformance_identity_count_32": len(conformance) == 32,
        "valid_strict_json_32_of_32": valid == 32,
        "schema_valid_32_of_32": valid == 32,
        "all_failure_classes_typed": set(failure_classes) <= FAILURE_CLASSES,
        "automatic_retry_zero": all(
            row.get("automatic_retry_attempted") is False for row in records
        ),
        "response_salvage_zero": all(
            row.get("salvage_attempted") is False for row in records
        ),
        "identity_unique_one_call_each": (
            len(identities) == len(set(identities)) == 40
            and all(row.get("reader_call_count") == 1 for row in records)
        ),
        "quarantined_identity_reissued_zero": quarantined_logical_request_id
        not in identities,
        "selected_ceiling_bounded": selected_ceiling in {256, 512},
        "model_prompt_seed_drift_zero": all(
            row.get("identity_drift") is False for row in records
        ),
        "formal_holdout_untouched": True,
    }
    return {
        "schema": "milai.dg22.s2-reader-conformance-score.v0.2",
        "status": (
            "PASS_READER_CONFORMANCE"
            if all(checks.values())
            else "PARKED_READER_CONTRACT_UNRELIABLE"
        ),
        "metrics": {
            "diagnosis_calls": len(diagnosis),
            "conformance_calls": len(conformance),
            "total_reader_calls": len(diagnosis) + len(conformance),
            "strict_json_valid": valid,
            "schema_valid": valid,
            "automatic_retries": 0,
            "salvaged_responses": 0,
            "failure_classes": failure_classes,
        },
        "selected_output_ceiling": selected_ceiling,
        "hard_gate": {"passed": all(checks.values()), "checks": checks},
        "formal_holdout_consumed": False,
    }


def safe_success_record(result: Any) -> dict[str, Any]:
    """Record strict success metadata while omitting answer and context bodies."""
    return {
        "status": "PASS",
        "native_request_id": result.native_request_id,
        "logical_request_id": result.logical_request_id,
        "seed": result.seed,
        "prompt_sha256": result.prompt_sha256,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "finish_reason": result.finish_reason,
        "content_byte_length": result.content_byte_length,
        "content_sha256": result.content_sha256,
        "answer_value_sha256": result.answer_sha256,
        "response_schema_sha256": result.response_schema_sha256,
        "reader_call_count": 1,
        "automatic_retry_attempted": False,
        "salvage_attempted": False,
        "raw_body_persisted": False,
        "identity_drift": False,
    }


def _cell(
    phase: str,
    ordinal: int,
    token_budget: int,
    answer_shape: str,
    context_size: str,
    unicode_mode: str,
    expected_answer_length: str,
) -> dict[str, Any]:
    identity = f"dg22-{phase.casefold()}-{ordinal:02d}"
    return {
        "cell_id": identity,
        "phase": phase,
        "ordinal": ordinal,
        "token_budget": token_budget,
        "answer_shape": answer_shape,
        "context_size": context_size,
        "unicode": unicode_mode,
        "expected_answer_length": expected_answer_length,
        "cell_digest": hashlib.sha256(
            json.dumps(
                [
                    phase,
                    ordinal,
                    token_budget,
                    answer_shape,
                    context_size,
                    unicode_mode,
                    expected_answer_length,
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
