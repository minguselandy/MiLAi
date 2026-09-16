#!/usr/bin/env python3
"""Run DG-23 S7 sealed matched Reader identities, then score post-seal."""

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
    DG14ProviderError,
    MatchedVllmProvider,
    ProviderResult,
    ReaderConformanceError,
)
from evals.dg23.matched_reader import (
    READER_SCHEMA,
    build_matched_reader_context_product,
    score_matched_reader_product,
    seal_matched_reader_context_product,
    seal_matched_reader_product,
)
from evals.dg23.reader_boundary import (
    FROZEN_READER_CONTRACT_SHA256,
    DG23ReaderBoundary,
    DG23ReaderBoundaryError,
    ExactReaderIdentityRegistry,
    ReaderAccountingReceipt,
    ReaderBoundaryResult,
    ReaderInputIdentity,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg23-s7-matched-reader-20260829-001")
    parser.add_argument("--reader-url", default="http://127.0.0.1:7860")
    parser.add_argument(
        "--resume-progress",
        type=Path,
        help="restore sealed exact identities from an interrupted no-retry run",
    )
    args = parser.parse_args()
    output = ROOT / "var/dg23/s7" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    plan_path = output / "plan.json"
    _write(
        plan_path,
        {
            "schema": "milai.dg23.s7-plan.v0.1",
            "run_id": args.run_id,
            "logical_cells": 240,
            "case_count": 10,
            "arms": 2,
            "modes": 4,
            "replicates": 3,
            "reader_contract_digest": FROZEN_READER_CONTRACT_SHA256,
            "reader_output_ceiling": 256,
            "exact_identity_reuse": True,
            "resume_progress": (
                _input_identity(args.resume_progress)
                if args.resume_progress is not None
                else None
            ),
            "automatic_retries": 0,
            "labels_before_reader_product_seal": False,
            "formal_holdout_consumed": False,
            "candidate_default": False,
        },
    )
    context_product = build_matched_reader_context_product(ROOT, run_id=args.run_id)
    context_path = output / "sealed-matched-reader-contexts.json"
    seal_matched_reader_context_product(context_product, context_path)

    registry = ExactReaderIdentityRegistry()
    boundary = DG23ReaderBoundary(
        MatchedVllmProvider(args.reader_url, max_output_tokens=256),
        registry=registry,
    )
    restore_receipt = (
        _restore_reader_progress(
            args.resume_progress,
            context_product=context_product,
            boundary=boundary,
            registry=registry,
        )
        if args.resume_progress is not None
        else {
            "status": "NO_PRIOR_PROGRESS",
            "restored_provider_calls": 0,
            "prior_completed_logical_cells": 0,
        }
    )
    completed: list[dict[str, Any]] = []
    progress_path = output / "reader-progress.json"
    infeasible_cells = 0
    invalid_json_count = 0
    for ordinal, source in enumerate(context_product["records"], start=1):
        record = dict(source)
        if source["readiness"] != "READY":
            infeasible_cells += 1
            record.update(
                {
                    "answer": "",
                    "provider": None,
                    "reader_source": "TYPED_BUDGET_INFEASIBLE_NO_CALL",
                    "reader_disposition": "NO_CALL_BUDGET_INFEASIBLE",
                    "reader_input_identity": None,
                }
            )
        else:
            try:
                result = boundary.read(
                    run_id=args.run_id,
                    case_id=str(source["case_id"]),
                    method_id=str(source["method_id"]),
                    presentation_budget=int(source["presentation_budget"]),
                    source_snapshot_digest=str(source["source_snapshot_digest"]),
                    replicate_index=int(source["replicate_index"]),
                    question=str(source["question"]),
                    question_as_of=str(source["question_as_of"]),
                    memory_context=str(source["context"]),
                    reader_context_digest=str(source["reader_context_digest"]),
                    estimated_tokens=int(source["estimated_tokens"]),
                    readiness=str(source["readiness"]),
                )
            except (DG14ProviderError, DG23ReaderBoundaryError) as exc:
                if (
                    isinstance(exc, ReaderConformanceError)
                    and exc.failure_class == "CONTENT_NOT_JSON"
                ):
                    invalid_json_count += 1
                _write(
                    output / "reader-failure.json",
                    {
                        "schema": "milai.dg23.s7-reader-failure.v0.1",
                        "run_id": args.run_id,
                        "logical_cell_ordinal": ordinal,
                        "case_id": source["case_id"],
                        "arm": source["arm"],
                        "mode": source["mode"],
                        "replicate_index": source["replicate_index"],
                        "reader_context_digest": source["reader_context_digest"],
                        "failure_type": type(exc).__name__,
                        "failure_code": getattr(
                            exc, "failure_class", getattr(exc, "reason_code", "UNKNOWN")
                        ),
                        "failure_metadata": getattr(exc, "metadata", {}),
                        "automatic_retries": 0,
                        "failed_cell_reusable": False,
                        "completed_valid_identities_reusable": True,
                        "formal_holdout_consumed": False,
                    },
                )
                raise
            record.update(
                {
                    "answer": result.provider_result.answer,
                    "provider": asdict(result.provider_result),
                    "reader_source": (
                        "FRESH_READER_CALL"
                        if result.disposition == "PROVIDER_CALL"
                        else (
                            "RESTORED_PROVIDER_CALL_RESULT"
                            if result.disposition == "RESTORED_PROVIDER_RESULT"
                            else "EXACT_IDENTITY_REUSE"
                        )
                    ),
                    "reader_disposition": result.disposition,
                    "reader_input_identity": asdict(result.identity),
                    "reader_accounting": asdict(result.accounting),
                    "logical_request_id": result.logical_request_id,
                }
            )
        completed.append(record)
        _write(
            progress_path,
            {
                "schema": "milai.dg23.s7-reader-progress.v0.1",
                "run_id": args.run_id,
                "completed_logical_cells": len(completed),
                "provider_calls": registry.provider_calls,
                "fresh_provider_calls": registry.fresh_provider_calls,
                "restored_provider_calls": registry.restored_provider_calls,
                "exact_identity_reuses": registry.exact_identity_reuses,
                "infeasible_cells": infeasible_cells,
                "automatic_retries": 0,
                "records": completed,
            },
        )
        print(
            json.dumps(
                {
                    "stage": "dg23-s7-reader",
                    "completed": len(completed),
                    "provider_calls": registry.provider_calls,
                    "exact_identity_reuses": registry.exact_identity_reuses,
                    "case_id": source["case_id"],
                    "arm": source["arm"],
                    "mode": source["mode"],
                    "replicate_index": source["replicate_index"],
                    "reader_source": record["reader_source"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    ready_identity_count = len(
        {
            (
                row["reader_context_digest"],
                row["sampling_seed"],
                FROZEN_READER_CONTRACT_SHA256,
            )
            for row in context_product["records"]
            if row["readiness"] == "READY"
        }
    )
    reader_product = {
        **{key: value for key, value in context_product.items() if key != "schema"},
        "schema": READER_SCHEMA,
        "status": "SEALED_READER_OUTPUTS_PENDING_SCORER",
        "records": completed,
        "reader_contract_digest": FROZEN_READER_CONTRACT_SHA256,
        "ready_exact_identity_count": ready_identity_count,
        "provider_calls": registry.provider_calls,
        "fresh_provider_calls": registry.fresh_provider_calls,
        "restored_provider_calls": registry.restored_provider_calls,
        "exact_identity_reuses": registry.exact_identity_reuses,
        "duplicate_reader_identity_call_count": (
            registry.provider_calls - ready_identity_count
        ),
        "infeasible_logical_cells": infeasible_cells,
        "infeasible_reader_calls": 0,
        "invalid_json_count": invalid_json_count,
        "automatic_retries": 0,
        "wrong_complete": 0,
        "resume": restore_receipt,
        "labels_loaded": False,
        "formal_holdout_consumed": False,
    }
    reader_path = output / "sealed-matched-reader-product.json"
    seal_matched_reader_product(reader_product, reader_path)
    score = score_matched_reader_product(ROOT, reader_path)
    score_path = output / "answer-score.json"
    _write(score_path, score)
    receipt = {
        "schema": "milai.dg23.s7-matched-reader-receipt.v0.1",
        "run_id": args.run_id,
        "status": score["status"],
        "hard_gate": score["hard_gate"],
        "summaries": score["summaries"],
        "provider_calls": registry.provider_calls,
        "fresh_provider_calls": registry.fresh_provider_calls,
        "restored_provider_calls": registry.restored_provider_calls,
        "exact_identity_reuses": registry.exact_identity_reuses,
        "ready_exact_identity_count": ready_identity_count,
        "infeasible_logical_cells": infeasible_cells,
        "infeasible_reader_calls": 0,
        "invalid_json_count": invalid_json_count,
        "automatic_retries": 0,
        "labels_loaded_only_after_reader_product_seal": True,
        "formal_holdout_consumed": False,
        "candidate_default": False,
        "resume": restore_receipt,
        "plan": _identity(plan_path),
        "sealed_context_product": _identity(context_path),
        "sealed_reader_product": _identity(reader_path),
        "answer_score": _identity(score_path),
        "reader_progress": _identity(progress_path),
    }
    receipt_path = output / "receipt.json"
    _write(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "hard_gate_passed": receipt["hard_gate"]["passed"],
                "provider_calls": receipt["provider_calls"],
                "exact_identity_reuses": receipt["exact_identity_reuses"],
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


def _input_identity(path: Path) -> dict[str, Any]:
    resolved = path if path.is_absolute() else ROOT / path
    resolved = resolved.resolve()
    if not resolved.is_file() or ROOT not in resolved.parents:
        raise ValueError("resume progress must be an existing workspace artifact")
    return _identity(resolved)


def _restore_reader_progress(
    path: Path,
    *,
    context_product: Mapping[str, Any],
    boundary: DG23ReaderBoundary,
    registry: ExactReaderIdentityRegistry,
) -> dict[str, Any]:
    """Restore prior successful identities after validating current exact inputs."""

    progress_identity = _input_identity(path)
    resolved = ROOT / str(progress_identity["path"])
    progress = json.loads(resolved.read_text(encoding="utf-8"))
    records = progress.get("records") if isinstance(progress, dict) else None
    if (
        not isinstance(progress, dict)
        or progress.get("schema") != "milai.dg23.s7-reader-progress.v0.1"
        or progress.get("automatic_retries") != 0
        or not isinstance(records, list)
        or progress.get("completed_logical_cells") != len(records)
    ):
        raise ValueError("resume progress is not a valid no-retry Reader checkpoint")
    eligible: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
    current_records = context_product.get("records")
    if not isinstance(current_records, list):
        raise TypeError("current Reader Context product is invalid")
    for row in current_records:
        if not isinstance(row, Mapping) or row.get("readiness") != "READY":
            continue
        key = (str(row["reader_context_digest"]), int(row["sampling_seed"]))
        eligible.setdefault(key, []).append(row)
    restored_digests: set[str] = set()
    for row in records:
        if not isinstance(row, Mapping):
            raise TypeError("resume progress contains a non-object record")
        raw_identity = row.get("reader_input_identity")
        raw_provider = row.get("provider")
        if raw_identity is None and raw_provider is None:
            continue
        if not isinstance(raw_identity, Mapping) or not isinstance(raw_provider, Mapping):
            raise TypeError("resume progress has an incomplete Reader result")
        identity = ReaderInputIdentity(
            reader_context_digest=str(raw_identity["reader_context_digest"]),
            reader_contract_digest=str(raw_identity["reader_contract_digest"]),
            sampling_seed=int(raw_identity["sampling_seed"]),
            generation_settings_digest=str(raw_identity["generation_settings_digest"]),
        )
        matches = eligible.get(
            (identity.reader_context_digest, identity.sampling_seed), []
        )
        if (
            not matches
            or identity.reader_contract_digest != boundary.reader_contract_digest
            or identity.generation_settings_digest
            != boundary.generation_settings_digest
        ):
            raise ValueError("restored Reader identity is absent from the current product")
        questions = {
            (str(match["question"]), str(match["question_as_of"]))
            for match in matches
        }
        contexts = {str(match["context"]) for match in matches}
        if len(questions) != 1 or len(contexts) != 1:
            raise ValueError("restored Reader identity maps to ambiguous current inputs")
        question, question_as_of = next(iter(questions))
        memory_context = next(iter(contexts))
        provider = ProviderResult(**dict(raw_provider))
        exact_reader_tokens = boundary.reader_tokens.memory_tokens(
            question=question,
            question_as_of=question_as_of,
            memory_context=memory_context,
        )
        if (
            provider.seed != identity.sampling_seed
            or provider.context_truncated
            or provider.context != memory_context
            or hashlib.sha256(provider.answer.encode()).hexdigest()
            != provider.answer_sha256
            or provider.memory_tokens != exact_reader_tokens
            or exact_reader_tokens > max(int(match["presentation_budget"]) for match in matches)
        ):
            raise ValueError("restored Reader result failed current identity validation")
        existing = registry.get(identity)
        if existing is not None:
            if existing.provider_result != provider:
                raise ValueError("restored exact identity has conflicting Provider results")
            continue
        accounting = ReaderAccountingReceipt(
            estimated_tokens=int(matches[0]["estimated_tokens"]),
            exact_reader_tokens=exact_reader_tokens,
            reader_tokenizer_path_or_id=str(boundary.tokenizer_path),
            reader_tokenizer_sha256=boundary.tokenizer_sha256,
            budget_ceiling=max(int(match["presentation_budget"]) for match in matches),
            accounting_delta=exact_reader_tokens
            - int(matches[0]["estimated_tokens"]),
            reader_chat_template_path_or_id=str(
                boundary.reader_tokens.chat_template_path
            ),
            reader_chat_template_sha256=(
                boundary.reader_tokens.chat_template_sha256
            ),
            reader_accounting_identity=boundary.reader_tokens.accounting_identity,
        )
        registry.restore(
            ReaderBoundaryResult(
                identity=identity,
                logical_request_id=str(
                    row.get("logical_request_id", provider.logical_request_id)
                ),
                provider_result=provider,
                accounting=accounting,
                disposition="PROVIDER_CALL",
            )
        )
        restored_digests.add(identity.identity_digest)
    if registry.restored_provider_calls != int(progress.get("provider_calls", -1)):
        raise ValueError("resume progress Provider-call count does not match unique identities")
    return {
        "status": "RESTORED_EXACT_IDENTITIES",
        "source_run_id": progress.get("run_id"),
        "prior_completed_logical_cells": len(records),
        "restored_provider_calls": registry.restored_provider_calls,
        "restored_identity_digests": sorted(restored_digests),
        "progress": progress_identity,
        "automatic_retries": 0,
    }


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
