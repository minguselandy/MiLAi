#!/usr/bin/env python3
"""Replay current ten cases against frozen DG-16 with only the P0 stop fix."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg14.benchmark import (
    DEFAULT_ENV_FILE,
    DEFAULT_TOKENIZER,
    _atomic_json,
    _local_token_counter,
)
from evals.dg14.provider import MatchedVllmProvider
from evals.dg16.lme10 import (
    BUDGETS,
    load_public_dev_labels,
)
from evals.dg17.measurement import (
    DG16_CONTEXTS_PATH,
    DG16_CONTEXTS_SHA256,
    DG16_RECEIPT_PATH,
    DG16_RECEIPT_SHA256,
    load_answer_bearing_labels,
    sha256_file,
)
from evals.paper.scorers.longmemeval import (
    score_answer,
    score_retrieval,
)
from scripts.run_dg16_lme10_compare import _run_milai_case
from scripts.run_dg16_q6 import _provider_record

METHOD_ID = "DG17-P0-SUFFICIENCY"
BASELINE_METHOD_ID = "DG16-MILAI-MCP"
MATCHED_PROVIDER_RUN_ID = "dg16-lme10-compare-20260827-002"


class DG17Q1RunError(RuntimeError):
    """The P0 matched replay failed or a frozen denominator drifted."""


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _load_baseline() -> tuple[dict[str, Any], dict[tuple[str, int], dict[str, Any]]]:
    if sha256_file(DG16_RECEIPT_PATH) != DG16_RECEIPT_SHA256:
        raise DG17Q1RunError("DG-16 receipt identity drifted")
    if sha256_file(DG16_CONTEXTS_PATH) != DG16_CONTEXTS_SHA256:
        raise DG17Q1RunError("DG-16 contexts identity drifted")
    receipt = json.loads(DG16_RECEIPT_PATH.read_text(encoding="utf-8"))
    contexts = json.loads(DG16_CONTEXTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict) or not isinstance(contexts, dict):
        raise DG17Q1RunError("DG-16 baseline artifacts are invalid")
    indexed = {
        (str(record["case_id"]), int(record["token_budget"])): record
        for record in contexts.get("records", [])
        if isinstance(record, dict)
        and record.get("method_id") == BASELINE_METHOD_ID
        and record.get("token_budget") in BUDGETS
    }
    if len(indexed) != 20:
        raise DG17Q1RunError("DG-16 baseline context denominator drifted")
    return receipt, indexed


def _coverage(
    context: Mapping[str, Any],
    label: Mapping[str, Any],
    scoring_label: Mapping[str, Any],
) -> dict[str, Any]:
    text = context.get("context")
    trace = context.get("retrieval_trace")
    atoms = label.get("atoms")
    if (
        not isinstance(text, str)
        or not isinstance(trace, list)
        or not isinstance(atoms, list)
    ):
        raise DG17Q1RunError("matched context lacks evidence accounting")
    normalized = _normalized(text)
    hit_atoms = [
        str(atom["atom_id"])
        for atom in atoms
        if _normalized(str(atom["span"]["text"])) in normalized
    ]
    retrieved_sessions = {
        str(item["session_id"])
        for item in trace
        if isinstance(item, dict) and isinstance(item.get("session_id"), str)
    }
    required_sessions = {str(value) for value in scoring_label["answer_session_ids"]}
    eligible = [atom for atom in atoms if str(atom["session_id"]) in retrieved_sessions]
    lost = [
        str(atom["atom_id"])
        for atom in eligible
        if str(atom["atom_id"]) not in set(hit_atoms)
    ]
    return {
        "answer_session_coverage": round(
            len(retrieved_sessions.intersection(required_sessions))
            / len(required_sessions),
            9,
        ),
        "required_evidence_set_coverage": round(len(hit_atoms) / len(atoms), 9),
        "retrieved_atom_ids": hit_atoms,
        "required_atom_count": len(atoms),
        "context_boundary_loss_rate": (
            round(len(lost) / len(eligible), 9) if eligible else None
        ),
        "boundary_eligible_atom_count": len(eligible),
        "boundary_lost_atom_ids": lost,
    }


def _status_from_context(context: str) -> str:
    for line in context.splitlines():
        if line.startswith("memory_status="):
            return line.partition("=")[2]
    raise DG17Q1RunError("compiled context lacks memory_status")


def _summaries(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: defaultdict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(str(record["policy"]), int(record["token_budget"]))].append(record)
    result: dict[str, Any] = {}
    for policy in ("DG16_ANY_EVIDENCE_STOP", "DG17_QUERY_SPECIFIC_STOP"):
        result[policy] = {}
        for budget in BUDGETS:
            cells = grouped[(policy, budget)]
            if len(cells) != 10:
                raise DG17Q1RunError("P0 summary denominator drifted")
            boundary_lost = sum(len(cell["boundary_lost_atom_ids"]) for cell in cells)
            boundary_eligible = sum(
                int(cell["boundary_eligible_atom_count"]) for cell in cells
            )
            result[policy][str(budget)] = {
                "case_count": 10,
                "exact_match_count": sum(
                    int(cell["answer_score"]["exact_match"]) for cell in cells
                ),
                "normalized_f1": round(
                    mean(
                        float(cell["answer_score"]["normalized_f1"]) for cell in cells
                    ),
                    9,
                ),
                "answer_session_coverage": round(
                    mean(float(cell["answer_session_coverage"]) for cell in cells), 9
                ),
                "required_evidence_set_coverage": round(
                    sum(len(cell["retrieved_atom_ids"]) for cell in cells)
                    / sum(int(cell["required_atom_count"]) for cell in cells),
                    9,
                ),
                "context_boundary_loss_rate": (
                    round(boundary_lost / boundary_eligible, 9)
                    if boundary_eligible
                    else None
                ),
                "premature_terminal_count": sum(
                    int(cell["premature_terminal"]) for cell in cells
                ),
                "typed_abstention_count": sum(
                    int(cell["memory_status"] == "ABSTAINED") for cell in cells
                ),
                "query_latency_ms_mean": round(
                    mean(float(cell["query_latency_ms"]) for cell in cells), 6
                ),
                "answer_path_latency_ms_mean": round(
                    mean(float(cell["answer_path_latency_ms"]) for cell in cells), 6
                ),
                "provider_calls": sum(
                    int(cell["provider"]["provider_calls"]) for cell in cells
                ),
                "automatic_retries": 0,
            }
    return result


def run(
    *,
    run_id: str,
    output_root: Path,
    reader_url: str,
    tokenizer_path: Path,
    env_file: Path,
    mcp_concurrency: int,
    projection_batch_size: int,
) -> dict[str, Any]:
    if output_root.exists():
        raise DG17Q1RunError("output exists; choose a fresh run ID")
    output_root.mkdir(parents=True)
    started = time.perf_counter()
    baseline_receipt, baseline_contexts = _load_baseline()
    _label_envelope, cases, labels = load_answer_bearing_labels()
    source_ids = tuple(case.case_id for case in cases)
    scoring_labels, scoring_identity = load_public_dev_labels(source_ids)
    token_counter = _local_token_counter(tokenizer_path)
    candidate_contexts: list[dict[str, Any]] = []
    lifecycle_records: list[dict[str, Any]] = []
    case_receipts: list[dict[str, Any]] = []
    for ordinal, case in enumerate(cases, start=1):
        case_root = output_root / "cases" / case.case_id
        case_root.mkdir(parents=True)
        contexts, lifecycle, receipt = _run_milai_case(
            case=case,
            run_id=run_id,
            case_root=case_root,
            token_counter=token_counter,
            env_file=env_file,
            mcp_concurrency=mcp_concurrency,
            projection_batch_size=projection_batch_size,
            cleanup_timeout_seconds=90.0,
            cleanup_readiness_timeout_ms=60_000,
            allowed_statuses=frozenset({"HIT", "PARTIAL", "ABSTAINED"}),
        )
        for context in contexts:
            context["method_id"] = METHOD_ID
        lifecycle["method_id"] = METHOD_ID
        candidate_contexts.extend(contexts)
        lifecycle_records.append(lifecycle)
        case_receipts.append(receipt)
        print(
            json.dumps(
                {
                    "stage": "p0-contexts",
                    "case": ordinal,
                    "case_count": 10,
                    "case_id": case.case_id,
                    "status": "SUCCEEDED",
                },
                sort_keys=True,
            ),
            flush=True,
        )
    if len(candidate_contexts) != 20:
        raise DG17Q1RunError("candidate context denominator drifted")
    _atomic_json(
        output_root / "contexts.json",
        {
            "schema": "milai.dg17.q1-p0-contexts.v0.1",
            "status": "SUCCEEDED",
            "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / CHARACTERIZATION",
            "formal_holdout_consumed": False,
            "record_count": 20,
            "records": candidate_contexts,
        },
    )

    provider = MatchedVllmProvider(reader_url)
    candidate_answers: dict[tuple[str, int], dict[str, Any]] = {}
    for case in cases:
        for budget in BUDGETS:
            context = next(
                item
                for item in candidate_contexts
                if item["case_id"] == case.case_id and item["token_budget"] == budget
            )
            answer = provider.answer(
                run_id=MATCHED_PROVIDER_RUN_ID,
                case_id=case.case_id,
                method_id=METHOD_ID,
                question=case.question,
                question_as_of=case.question_at,
                memory_context=str(context["context"]),
                token_budget=budget,
            )
            candidate_answers[(case.case_id, budget)] = {
                "answer": answer.answer,
                "provider": _provider_record(answer),
            }

    baseline_records = {
        (str(item["case_id"]), int(item["token_budget"])): item
        for item in baseline_receipt["records"]
        if item["method_id"] == BASELINE_METHOD_ID and item["token_budget"] in BUDGETS
    }
    records: list[dict[str, Any]] = []
    for case in cases:
        label = labels[case.case_id]
        scoring = scoring_labels[case.case_id]
        for budget in BUDGETS:
            for policy, context, answer_record in (
                (
                    "DG16_ANY_EVIDENCE_STOP",
                    baseline_contexts[(case.case_id, budget)],
                    baseline_records[(case.case_id, budget)],
                ),
                (
                    "DG17_QUERY_SPECIFIC_STOP",
                    next(
                        item
                        for item in candidate_contexts
                        if item["case_id"] == case.case_id
                        and item["token_budget"] == budget
                    ),
                    candidate_answers[(case.case_id, budget)],
                ),
            ):
                coverage = _coverage(context, label, scoring)
                answer_score = score_answer(
                    str(answer_record["answer"]), scoring["answers"]
                )
                retrieval_score = score_retrieval(
                    context["retrieval_trace"], scoring["answer_session_ids"]
                )
                memory_status = _status_from_context(str(context["context"]))
                completeness_required = (
                    label["gold_ir"]["completeness"] != "TOP_K_ACCEPTABLE"
                )
                premature = (
                    completeness_required
                    and coverage["required_evidence_set_coverage"] < 1.0
                    and context["usage"].get("retrieval_terminal_stage")
                    == "EVIDENCE_FTS"
                )
                provider_record = answer_record["provider"]
                records.append(
                    {
                        "case_id": case.case_id,
                        "query_class": label["gold_ir"]["query_class"],
                        "operator": label["gold_ir"]["operator"],
                        "token_budget": budget,
                        "policy": policy,
                        "memory_status": memory_status,
                        "retrieval_terminal_stage": context["usage"].get(
                            "retrieval_terminal_stage"
                        ),
                        "sufficiency_decision": context["usage"].get(
                            "sufficiency_decision"
                        ),
                        "retrieval_attempted_stages": context["usage"].get(
                            "retrieval_attempted_stages"
                        ),
                        "premature_terminal": premature,
                        "answer": answer_record["answer"],
                        "answer_score": answer_score,
                        "retrieval_score": retrieval_score,
                        "query_latency_ms": context["query_latency_ms"],
                        "answer_path_latency_ms": round(
                            float(context["query_latency_ms"])
                            + float(provider_record["tokenize_latency_ms"])
                            + float(provider_record["provider_latency_ms"]),
                            6,
                        ),
                        "provider": provider_record,
                        **coverage,
                    }
                )
    if len(records) != 40:
        raise DG17Q1RunError("matched record denominator drifted")
    summaries = _summaries(records)
    receipt = {
        "schema": "milai.dg17.q1-p0-matched.v0.1",
        "status": "CHARACTERIZED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / CHARACTERIZATION",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "formal_source_id_overlap": [],
        "configuration": {
            "case_count": 10,
            "token_budgets": list(BUDGETS),
            "same_provider_prompt_generation": True,
            "matched_provider_run_id": MATCHED_PROVIDER_RUN_ID,
            "automatic_retries": 0,
            "candidate_change_scope": "DG17_P0_SUFFICIENCY_ONLY",
        },
        "baseline": {
            "receipt_path": str(DG16_RECEIPT_PATH.relative_to(ROOT)),
            "receipt_sha256": DG16_RECEIPT_SHA256,
            "contexts_path": str(DG16_CONTEXTS_PATH.relative_to(ROOT)),
            "contexts_sha256": DG16_CONTEXTS_SHA256,
        },
        "label_source": scoring_identity,
        "summaries": summaries,
        "records": records,
        "lifecycle_records": lifecycle_records,
        "case_receipt_count": len(case_receipts),
        "experiment_wall_ms": round((time.perf_counter() - started) * 1_000, 6),
    }
    _atomic_json(output_root / "receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--reader-url", default="http://127.0.0.1:7860")
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--mcp-concurrency", type=int, default=4)
    parser.add_argument("--projection-batch-size", type=int, default=32)
    args = parser.parse_args()
    output_root = args.output_root or ROOT / "var/dg17/q1" / args.run_id
    receipt = run(
        run_id=args.run_id,
        output_root=output_root,
        reader_url=args.reader_url,
        tokenizer_path=args.tokenizer,
        env_file=args.env_file,
        mcp_concurrency=args.mcp_concurrency,
        projection_batch_size=args.projection_batch_size,
    )
    receipt_path = output_root / "receipt.json"
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(receipt_path.relative_to(ROOT)),
                "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                "summaries": receipt["summaries"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
