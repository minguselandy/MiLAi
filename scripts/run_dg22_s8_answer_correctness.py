#!/usr/bin/env python3
"""Execute the frozen DG-22 S8 baseline-reuse vs candidate Reader comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from evals.dg14.provider import (
    MatchedVllmProvider,
    full_provider_contract_sha256,
    logical_request_id,
    matched_seed,
)
from evals.dg20.matched_q6_eval import _matched_causal_reader_records
from evals.dg22.answer_correctness import (
    BASELINE_ARM,
    CANDIDATE_ARM,
    DG20_PRODUCT,
    DG20_SOURCE_ARM,
    READER_SCHEMA,
    S7_RECEIPT,
    build_answer_context_product,
    score_answer_reader_product,
    seal_answer_context_product,
    seal_answer_reader_product,
)

SEED_RUN_ID = "dg20-s5-matched-q6-20260828-002"
QUARANTINE = (
    ROOT / "var/dg22/s0/dg22-s0-baseline-freeze-20260829-001/reader-quarantine.json"
)
PRIOR_READER_PRODUCT = ROOT / (
    "var/dg22/s8/dg22-s8-answer-correctness-20260829-001/"
    "sealed-answer-reader-product.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="dg22-s8-answer-correctness-20260829-001")
    parser.add_argument("--reader-url", default="http://127.0.0.1:7860")
    args = parser.parse_args()
    output = ROOT / "var/dg22/s8" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg22.s8-plan.v0.1",
            "run_id": args.run_id,
            "baseline_reuses": 20,
            "candidate_reader_call_ceiling": 20,
            "candidate_exact_identity_reuse_allowed": True,
            "reader_output_ceiling": 256,
            "automatic_retries": 0,
            "retrieval_and_packing_frozen": True,
            "formal_holdout_consumed": False,
        },
    )
    context_product = build_answer_context_product(ROOT, run_id=args.run_id)
    context_path = output / "sealed-answer-contexts.json"
    seal_answer_context_product(context_product, context_path)

    dg20 = _read(ROOT / DG20_PRODUCT)
    paired_dg20, pairing = _matched_causal_reader_records(dg20["records"])
    baseline_source = {
        (str(row["case_id"]), int(row["token_budget"])): row
        for row in paired_dg20
        if row.get("arm") == DG20_SOURCE_ARM
    }
    prior_index: dict[tuple[str, int, str, int], dict[str, Any]] = {}
    if PRIOR_READER_PRODUCT.exists() and PRIOR_READER_PRODUCT.parent != output:
        prior_product = _read(PRIOR_READER_PRODUCT)
        if (
            prior_product.get("provider_contract_sha256")
            == full_provider_contract_sha256()
        ):
            prior_index = {
                (
                    str(row["case_id"]),
                    int(row["token_budget"]),
                    str(row["context_sha256"]),
                    int(row["provider"]["seed"]),
                ): row
                for row in prior_product["records"]
                if row.get("arm") == CANDIDATE_ARM
                and isinstance(row.get("provider"), dict)
            }
    quarantine = _read(QUARANTINE)
    provider = MatchedVllmProvider(args.reader_url, max_output_tokens=256)
    completed: list[dict[str, Any]] = []
    attempted_identities: set[tuple[str, str, int, str, int]] = set()
    observed_identities: set[tuple[str, str, int, str, int]] = set()
    progress_path = output / "reader-progress.json"
    reader_calls = 0
    for row in context_product["records"]:
        record = dict(row)
        key = (row["case_id"], row["token_budget"])
        if row["arm"] == BASELINE_ARM:
            source = baseline_source[key]
            record["answer"] = source["answer"]
            record["provider"] = source["provider"]
            record["reader_source"] = "DG20_EXACT_CONTEXT_CONTRACT_SEED_REUSE"
        else:
            request_id = logical_request_id(
                SEED_RUN_ID,
                row["case_id"],
                CANDIDATE_ARM,
                row["token_budget"],
            )
            seed = matched_seed(SEED_RUN_ID, row["case_id"], row["token_budget"])
            identity = (
                request_id,
                row["context_sha256"],
                seed,
                full_provider_contract_sha256(),
                row["token_budget"],
            )
            if request_id == quarantine["logical_request_id"]:
                raise RuntimeError("DG22_S8_QUARANTINED_IDENTITY_REISSUE")
            if identity in attempted_identities:
                raise RuntimeError("DG22_S8_DUPLICATE_READER_IDENTITY")
            if identity in observed_identities:
                raise RuntimeError("DG22_S8_DUPLICATE_READER_IDENTITY")
            observed_identities.add(identity)
            prior_record = prior_index.get(
                (row["case_id"], row["token_budget"], row["context_sha256"], seed)
            )
            if prior_record is not None:
                if prior_record["context"] != row["context"]:
                    raise RuntimeError("DG22_S8_READER_REUSE_DIGEST_COLLISION")
                record["answer"] = prior_record["answer"]
                record["provider"] = prior_record["provider"]
                record["reader_source"] = "S8_EXACT_CONTEXT_CONTRACT_SEED_REUSE"
            else:
                attempted_identities.add(identity)
                reader_calls += 1
                try:
                    result = provider.answer(
                        run_id=SEED_RUN_ID,
                        case_id=row["case_id"],
                        method_id=CANDIDATE_ARM,
                        question=row["question"],
                        question_as_of=row["question_as_of"],
                        memory_context=row["context"],
                        token_budget=row["token_budget"],
                    )
                except Exception as exc:
                    _write(
                        output / "reader-failure.json",
                        {
                            "schema": "milai.dg22.s8-reader-failure.v0.1",
                            "run_id": args.run_id,
                            "logical_request_id": request_id,
                            "context_sha256": row["context_sha256"],
                            "failure_type": type(exc).__name__,
                            "automatic_retries": 0,
                            "reusable": False,
                        },
                    )
                    raise
                if result.context != row["context"] or result.context_truncated:
                    raise RuntimeError("DG22_S8_READER_MODIFIED_FROZEN_CONTEXT")
                record["answer"] = result.answer
                record["provider"] = asdict(result)
                record["reader_source"] = "FROZEN_READER_ONE_CALL_AFTER_CONTEXT_SEAL"
        completed.append(record)
        _write(
            progress_path,
            {
                "schema": "milai.dg22.s8-reader-progress.v0.1",
                "run_id": args.run_id,
                "completed_count": len(completed),
                "reader_calls": reader_calls,
                "records": completed,
            },
        )
        print(
            json.dumps(
                {
                    "stage": "dg22-s8-reader",
                    "completed": len(completed),
                    "case_id": row["case_id"],
                    "budget": row["token_budget"],
                    "arm": row["arm"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    reader_product = {
        **{key: value for key, value in context_product.items() if key != "schema"},
        "schema": READER_SCHEMA,
        "status": "READER_COMPLETE_UNSCORED",
        "records": completed,
        "baseline_reader_reuses": 20,
        "candidate_reader_calls": reader_calls,
        "candidate_reader_reuses": 20 - reader_calls,
        "reader_identity_count": len(observed_identities),
        "duplicate_reader_identity_count": 20 - len(observed_identities),
        "dg20_causal_reader_pairing": pairing,
        "provider_contract_sha256": full_provider_contract_sha256(),
        "automatic_retries": 0,
        "wrong_complete": _read(ROOT / S7_RECEIPT)["metrics"]["wrong_complete"],
    }
    reader_path = output / "sealed-answer-reader-product.json"
    seal_answer_reader_product(reader_product, reader_path)
    score = score_answer_reader_product(reader_path)
    score_path = output / "answer-score.json"
    _write(score_path, score)
    receipt = {
        "schema": "milai.dg22.s8-answer-receipt.v0.1",
        "run_id": args.run_id,
        "status": score["status"],
        "hard_gate": score["hard_gate"],
        "summaries": score["summaries"],
        "reader_calls": reader_calls,
        "baseline_reader_reuses": 20,
        "candidate_reader_reuses": 20 - reader_calls,
        "automatic_retries": 0,
        "plan": _identity(plan_path),
        "sealed_answer_contexts": _identity(context_path),
        "sealed_answer_reader_product": _identity(reader_path),
        "answer_score": _identity(score_path),
        "reader_progress": _identity(progress_path),
        "formal_holdout_consumed": False,
    }
    receipt_path = output / "receipt.json"
    _write(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "summaries": receipt["summaries"],
                "receipt": str(receipt_path.relative_to(ROOT)),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if receipt["hard_gate"]["passed"] else 2


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
