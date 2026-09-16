#!/usr/bin/env python3
"""Run the narrow DG-16 Reader/Exact-Match stability diagnostic lane."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg14.benchmark import _atomic_json, load_opened_dev
from evals.dg14.provider import MatchedVllmProvider, ProviderResult
from evals.dg16.q0 import load_evaluation_fixture
from evals.dg16.reader_stability import (
    ReaderStabilityError,
    artifact_forensics,
    find_record,
    prompt_sha256,
    reconstruct_context,
)
from evals.paper.provider import MODEL_ID
from evals.paper.scorers.longmemeval import score_answer
from scripts.run_dg16_q6 import DG14_PROVIDER_SEED_RUN_ID

CASE_ID = "031748ae"
TOKEN_BUDGET = 2048
Q6_RECEIPT = ROOT / "var/dg16/q6/dg16-q6-product-20260827-006/receipt.json"
Q6_RECEIPT_SHA256 = "de64fae56a931afdac0bc6db80ba6471beffe68016fdcf641984d5ef70b685da"
LME_RECEIPT = ROOT / "var/dg16/lme/dg16-lme-effect-20260827-003/receipt.json"
LME_RECEIPT_SHA256 = "d8a368aaeccdd16341656e80147e4250a413e779a2f90eb09650ebbc44f17183"
DEFAULT_OUTPUT_ROOT = ROOT / "var/dg16/reader-stability"


class ReaderStabilityRunError(RuntimeError):
    """The bounded diagnostic could not produce a valid receipt."""


@dataclass(frozen=True, slots=True)
class Arm:
    arm_id: str
    context_source: str
    memory_context: str
    method_id: str
    repetitions: int


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_bound_json(path: Path, expected_sha256: str) -> dict[str, Any]:
    observed = _sha256(path)
    if observed != expected_sha256:
        raise ReaderStabilityRunError(f"bound artifact drifted: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReaderStabilityRunError(f"bound artifact is not an object: {path}")
    return value


def _reader_identity(base_url: str) -> dict[str, Any]:
    normalized = base_url.rstrip("/").removesuffix("/v1")
    if normalized not in {"http://127.0.0.1:7860", "http://localhost:7860"}:
        raise ReaderStabilityRunError("Reader must be the existing loopback vLLM")
    with urllib.request.urlopen(f"{normalized}/v1/models", timeout=30) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ReaderStabilityRunError("Reader model identity exceeded 4 MiB")
    value = json.loads(raw)
    models = value.get("data") if isinstance(value, dict) else None
    if not isinstance(models, list) or len(models) != 1:
        raise ReaderStabilityRunError("Reader model identity is not singular")
    model = models[0]
    if not isinstance(model, Mapping) or model.get("id") != MODEL_ID:
        raise ReaderStabilityRunError("Reader model identity drifted")
    return {
        key: model.get(key)
        for key in ("id", "created", "owned_by", "root", "max_model_len")
    }


def _provider_record(result: ProviderResult) -> dict[str, Any]:
    value = asdict(result)
    context = str(value.pop("context"))
    value["context_sha256"] = hashlib.sha256(context.encode()).hexdigest()
    return value


def _case_answers(fixture: Mapping[str, Any]) -> list[str]:
    cases = fixture.get("cases")
    if not isinstance(cases, list):
        raise ReaderStabilityRunError("scoring fixture lacks cases")
    selected = [
        item
        for item in cases
        if isinstance(item, Mapping) and item.get("case_id") == CASE_ID
    ]
    if len(selected) != 1 or not isinstance(selected[0].get("answers"), list):
        raise ReaderStabilityRunError("scoring fixture cell is not unique")
    answers = selected[0]["answers"]
    if not answers or any(not isinstance(answer, str) for answer in answers):
        raise ReaderStabilityRunError("scoring fixture answers are malformed")
    return list(answers)


def _summarize_arm(records: list[dict[str, Any]]) -> dict[str, Any]:
    answers = [str(record["answer"]) for record in records]
    exact = [int(record["answer_score"]["exact_match"]) for record in records]
    f1 = [float(record["answer_score"]["normalized_f1"]) for record in records]
    return {
        "repetition_count": len(records),
        "answer_variant_count": len(set(answers)),
        "answer_variants": sorted(set(answers)),
        "same_payload_output_stable": len(set(answers)) == 1,
        "exact_match_count": sum(exact),
        "exact_match_rate": round(mean(exact), 9),
        "normalized_f1_mean": round(mean(f1), 9),
        "normalized_f1_min": min(f1),
    }


def _singleton_answer(arms: Mapping[str, Mapping[str, Any]], arm_id: str) -> str | None:
    variants = arms[arm_id]["summary"]["answer_variants"]
    return (
        str(variants[0]) if isinstance(variants, list) and len(variants) == 1 else None
    )


def _diagnosis(
    forensics: Mapping[str, Any], arms: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    q6_answer = _singleton_answer(arms, "q6_original_payload")
    lme_answer = _singleton_answer(arms, "lme_original_payload")
    q6_swap = _singleton_answer(arms, "q6_context_lme_salt")
    lme_swap = _singleton_answer(arms, "lme_context_q6_salt")
    repeated_payloads_stable = q6_answer is not None and lme_answer is not None
    salt_swap_invariant = (
        repeated_payloads_stable and q6_swap == q6_answer and lme_swap == lme_answer
    )
    context_variant_observed = repeated_payloads_stable and q6_answer != lme_answer
    if not repeated_payloads_stable:
        disposition = "LIVE_SAME_PAYLOAD_READER_VARIABILITY_SIGNAL"
    elif not salt_swap_invariant:
        disposition = "LIVE_CACHE_SALT_SENSITIVITY_SIGNAL"
    elif (
        forensics.get("opaque_evidence_id_only_context_drift")
        and context_variant_observed
    ):
        disposition = "OPAQUE_EVIDENCE_ID_PROMPT_SENSITIVITY_SIGNAL"
    elif forensics.get("opaque_evidence_id_only_context_drift"):
        disposition = "HISTORICAL_UUID_PROMPT_DRIFT_LIVE_OUTPUT_VARIANT_NOT_REPRODUCED"
    else:
        disposition = "BOUNDED_DIAGNOSTIC_INCONCLUSIVE"
    return {
        "disposition": disposition,
        "repeated_original_payloads_stable": repeated_payloads_stable,
        "cache_salt_swap_output_invariant": salt_swap_invariant,
        "q6_vs_lme_context_output_variant_observed_live": context_variant_observed,
        "retrieval_rework_indicated": False,
        "scope_note": (
            "Opened-development single-case diagnostic; this isolates Reader input "
            "and strict scorer behavior and is not a generalization claim."
        ),
    }


def run_diagnostic(
    *,
    run_id: str,
    output_root: Path,
    reader_url: str,
    repetitions: int,
) -> dict[str, Any]:
    if output_root.exists():
        raise ReaderStabilityRunError("output exists; choose a fresh run ID")
    if not 2 <= repetitions <= 5:
        raise ReaderStabilityRunError("repetitions must be between 2 and 5")
    output_root.mkdir(parents=True)

    q6_receipt = _load_bound_json(Q6_RECEIPT, Q6_RECEIPT_SHA256)
    lme_receipt = _load_bound_json(LME_RECEIPT, LME_RECEIPT_SHA256)
    _partition, cases = load_opened_dev()
    case = next((item for item in cases if item.case_id == CASE_ID), None)
    if case is None:
        raise ReaderStabilityRunError("opened-development case is missing")
    q6_record = find_record(q6_receipt, case_id=CASE_ID, token_budget=TOKEN_BUDGET)
    lme_record = find_record(lme_receipt, case_id=CASE_ID, token_budget=TOKEN_BUDGET)
    q6_context = reconstruct_context(q6_record, case.history_events)
    lme_context = reconstruct_context(lme_record, case.history_events)
    for record, context in ((q6_record, q6_context), (lme_record, lme_context)):
        provider = record.get("provider")
        if not isinstance(provider, Mapping):
            raise ReaderStabilityRunError("source record lacks provider identity")
        observed_prompt_sha = prompt_sha256(
            question=case.question,
            question_as_of=case.question_at,
            memory_context=context.text,
        )
        if observed_prompt_sha != provider.get("prompt_sha256"):
            raise ReaderStabilityRunError(
                "reconstructed historical prompt hash differs"
            )

    forensics = artifact_forensics(q6_record, lme_record, q6_context, lme_context)
    q6_method = str(q6_record["method_id"])
    lme_method = str(lme_record["method_id"])
    arms = (
        Arm("q6_original_payload", "q6", q6_context.text, q6_method, repetitions),
        Arm("lme_original_payload", "lme", lme_context.text, lme_method, repetitions),
        Arm("q6_context_lme_salt", "q6", q6_context.text, lme_method, 1),
        Arm("lme_context_q6_salt", "lme", lme_context.text, q6_method, 1),
        Arm(
            "stable_evidence_id_payload",
            "stable-evidence-id",
            q6_context.stable_id_text,
            "DG16-READER-STABILITY-STABLE-ID",
            repetitions,
        ),
    )
    reader_identity = _reader_identity(reader_url)
    provider = MatchedVllmProvider(reader_url)

    raw_records: dict[str, list[dict[str, Any]]] = {}
    for arm in arms:
        arm_records: list[dict[str, Any]] = []
        for repetition in range(1, arm.repetitions + 1):
            result = provider.answer(
                run_id=DG14_PROVIDER_SEED_RUN_ID,
                case_id=CASE_ID,
                method_id=arm.method_id,
                question=case.question,
                question_as_of=case.question_at,
                memory_context=arm.memory_context,
                token_budget=TOKEN_BUDGET,
            )
            arm_records.append(
                {
                    "repetition": repetition,
                    "answer": result.answer,
                    "provider": _provider_record(result),
                }
            )
        raw_records[arm.arm_id] = arm_records

    # Labels enter only after every Reader call has terminated.
    answers = _case_answers(load_evaluation_fixture())
    scored_arms: dict[str, dict[str, Any]] = {}
    for arm in arms:
        records = raw_records[arm.arm_id]
        for record in records:
            record["answer_score"] = score_answer(str(record["answer"]), answers)
        scored_arms[arm.arm_id] = {
            "context_source": arm.context_source,
            "context_sha256": hashlib.sha256(arm.memory_context.encode()).hexdigest(),
            "method_id": arm.method_id,
            "cache_salt_policy": "provider logical request identity",
            "records": records,
            "summary": _summarize_arm(records),
        }

    historical_q6_score = q6_record.get("answer_score")
    historical_lme_score = lme_record.get("answer_score")
    strict_boundary = bool(
        isinstance(historical_q6_score, Mapping)
        and isinstance(historical_lme_score, Mapping)
        and historical_q6_score.get("exact_match") == 1
        and historical_lme_score.get("exact_match") == 0
        and float(historical_lme_score.get("normalized_f1", 0.0)) >= 0.95
        and q6_record.get("evidence_atom_recall") == 1
        and lme_record.get("evidence_atom_recall") == 1
    )
    receipt = {
        "run_id": run_id,
        "status": "CHARACTERIZED",
        "scope": {
            "case_id": CASE_ID,
            "token_budget": TOKEN_BUDGET,
            "partition": "LME-OPENED-SMOKE",
            "formal_holdout": False,
        },
        "source_artifacts": {
            "q6_receipt": {
                "path": str(Q6_RECEIPT.relative_to(ROOT)),
                "sha256": Q6_RECEIPT_SHA256,
            },
            "post_goal_lme_receipt": {
                "path": str(LME_RECEIPT.relative_to(ROOT)),
                "sha256": LME_RECEIPT_SHA256,
            },
        },
        "environment": {
            "reader": reader_identity,
            "service_mutation": "NONE",
            "provider_seed_run_id": DG14_PROVIDER_SEED_RUN_ID,
        },
        "execution_contract": {
            "retrieval_calls": 0,
            "runtime_or_database_started": False,
            "automatic_retries": 0,
            "predeclared_provider_calls": sum(arm.repetitions for arm in arms),
            "temperature": 0,
            "top_p": 1,
            "same_seed_policy": True,
            "labels_loaded_after_provider_calls": True,
        },
        "artifact_forensics": forensics,
        "historical_strict_em_boundary": {
            "observed": strict_boundary,
            "q6_answer": q6_record.get("answer"),
            "q6_answer_score": historical_q6_score,
            "post_goal_lme_answer": lme_record.get("answer"),
            "post_goal_lme_answer_score": historical_lme_score,
            "both_evidence_atom_recall": [
                q6_record.get("evidence_atom_recall"),
                lme_record.get("evidence_atom_recall"),
            ],
            "interpretation": (
                "The frozen strict scorer changes EM on a near-exact lexical variant "
                "while both runs retain full required Evidence atom recall."
            ),
        },
        "arms": scored_arms,
        "diagnosis": _diagnosis(forensics, scored_arms),
    }
    _atomic_json(output_root / "receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--reader-url", default="http://127.0.0.1:7860")
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    try:
        receipt = run_diagnostic(
            run_id=args.run_id,
            output_root=output_root,
            reader_url=args.reader_url,
            repetitions=args.repetitions,
        )
    except (ReaderStabilityError, ReaderStabilityRunError, OSError, ValueError) as exc:
        if output_root.exists():
            _atomic_json(
                output_root / "failure.json",
                {
                    "run_id": args.run_id,
                    "status": "FAILED",
                    "failure_type": type(exc).__name__,
                    "failure": str(exc),
                },
            )
        raise
    receipt_path = (output_root / "receipt.json").resolve()
    try:
        display_path = receipt_path.relative_to(ROOT)
    except ValueError:
        display_path = receipt_path
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "disposition": receipt["diagnosis"]["disposition"],
                "receipt": str(display_path),
                "receipt_sha256": _sha256(receipt_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
