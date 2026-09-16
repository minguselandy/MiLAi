"""Pure contracts and analysis for the DG-16 ten-case LME comparison lane."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import mean, median
from typing import Any

from evals.dg14.benchmark import ROOT, OpenedDevCase, _dg14_event
from evals.dg14.dev_split import FORMAL_CONSUMPTION_PATHS
from evals.paper.datasets.longmemeval import labels_from_dataset, load_inputs
from evals.paper.scorers.longmemeval import score_answer, score_retrieval

FULL_LABEL_FREE_INPUTS = ROOT / "var/dg11/paper/freeze/longmemeval-full-inputs.json"
PUBLIC_DEV_SPLIT = ROOT / "var/dg14/splits/public-deidentified-dev-v1/source-ids.json"
LABEL_SOURCE = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
EXPECTED_FULL_INPUT_SHA256 = (
    "7c1c3a61cc81ddf523e8355a02ac2ba9ed4f517fc09cf9609cc7aeaa062fa412"
)
EXPECTED_PUBLIC_DEV_SHA256 = (
    "91f502f79850b3dfb952c7094bc632615f6f69d8e40b8350ef292681b03913d2"
)
EXPECTED_LABEL_SOURCE_SHA256 = (
    "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
)
METHODS = ("DG16-MILAI-MCP", "LME-BM25-T")
BUDGETS = (512, 2048)


class DG16LME10Error(RuntimeError):
    """The ten-case selection, label boundary, or denominator drifted."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DG16LME10Error(f"invalid JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise DG16LME10Error(f"JSON object required: {path}")
    return value


def load_public_dev_cases(
    case_count: int = 10,
) -> tuple[tuple[OpenedDevCase, ...], dict[str, Any]]:
    """Load a deterministic label-free subset after proving holdout exclusion."""

    if case_count != 10:
        raise DG16LME10Error("this diagnostic lane is frozen to ten cases")
    identities = {
        "full_label_free_inputs": sha256_file(FULL_LABEL_FREE_INPUTS),
        "public_dev_split": sha256_file(PUBLIC_DEV_SPLIT),
    }
    if identities != {
        "full_label_free_inputs": EXPECTED_FULL_INPUT_SHA256,
        "public_dev_split": EXPECTED_PUBLIC_DEV_SHA256,
    }:
        raise DG16LME10Error("frozen label-free selection identity drifted")
    if any(path.exists() for path in FORMAL_CONSUMPTION_PATHS):
        raise DG16LME10Error("formal holdout consumption marker exists")

    split = _json_object(PUBLIC_DEV_SPLIT)
    source_ids = split.get("source_ids")
    if (
        split.get("schema") != "milai.dg14.public-deidentified-dev-split.v1"
        or split.get("formal_holdout_consumed") is not False
        or split.get("formal_source_id_overlap") != []
        or not isinstance(source_ids, list)
        or len(source_ids) < case_count
    ):
        raise DG16LME10Error("public development split contract drifted")
    selected_ids = tuple(str(value) for value in source_ids[:case_count])
    if len(set(selected_ids)) != case_count:
        raise DG16LME10Error("selected public development IDs are not unique")

    partition, raw_cases = load_inputs(FULL_LABEL_FREE_INPUTS)
    if partition != "LME-FULL-500-CHARACTERIZATION":
        raise DG16LME10Error("full label-free partition identity drifted")
    by_id = {case.source_id: case for case in raw_cases}
    if any(source_id not in by_id for source_id in selected_ids):
        raise DG16LME10Error("public development case is absent from label-free inputs")
    cases: list[OpenedDevCase] = []
    for source_id in selected_ids:
        case = by_id[source_id]
        cases.append(
            OpenedDevCase(
                case_id=case.source_id,
                category=case.category,
                question=case.question,
                question_at=case.question_at,
                sessions=case.sessions,
                history_events=tuple(
                    _dg14_event(
                        case,
                        session_ordinal=session_ordinal,
                        turn_ordinal=turn_ordinal,
                    )
                    for session_ordinal, session in enumerate(case.sessions)
                    for turn_ordinal, _turn in enumerate(session.turns)
                ),
            )
        )
    selection = {
        "classification": split["classification"],
        "case_count": case_count,
        "source_ids": list(selected_ids),
        "selection_policy": split["selection_policy"],
        "formal_source_id_overlap": [],
        "formal_holdout_consumed": False,
        "identities": identities,
    }
    return tuple(cases), selection


def load_public_dev_labels(
    source_ids: tuple[str, ...],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Open only the selected public-dev labels after product execution."""

    if len(source_ids) != 10 or len(set(source_ids)) != 10:
        raise DG16LME10Error("label opening requires the frozen ten-case denominator")
    observed = sha256_file(LABEL_SOURCE)
    if observed != EXPECTED_LABEL_SOURCE_SHA256:
        raise DG16LME10Error("LongMemEval public label source identity drifted")
    labels = labels_from_dataset(LABEL_SOURCE, source_ids)
    return labels, {
        "path": str(LABEL_SOURCE),
        "sha256": observed,
    }


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise DG16LME10Error("cannot summarize an empty metric")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def score_records(
    records: Sequence[Mapping[str, Any]],
    labels: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Score the sealed paired records with answer and session-level retrieval labels."""

    expected = {
        (case_id, method_id, budget)
        for case_id in labels
        for method_id in METHODS
        for budget in BUDGETS
    }
    observed = [
        (
            str(record.get("case_id")),
            str(record.get("method_id")),
            int(record.get("token_budget", -1)),
        )
        for record in records
    ]
    if len(labels) != 10 or len(records) != 40 or set(observed) != expected:
        raise DG16LME10Error("paired product record denominator drifted")
    if len(set(observed)) != len(observed):
        raise DG16LME10Error("paired product records contain duplicate cells")

    scored: list[dict[str, Any]] = []
    for record in records:
        case_id = str(record["case_id"])
        label = labels[case_id]
        answers = label.get("answers")
        relevant_sessions = label.get("answer_session_ids")
        trace = record.get("retrieval_trace")
        if (
            not isinstance(answers, list)
            or not answers
            or not isinstance(relevant_sessions, list)
            or not relevant_sessions
            or not isinstance(trace, list)
        ):
            raise DG16LME10Error("public development scoring label is malformed")
        answer_score = score_answer(
            str(record["answer"]), [str(answer) for answer in answers]
        )
        retrieval_score = score_retrieval(
            trace,
            [str(session_id) for session_id in relevant_sessions],
        )
        scored.append(
            {
                **dict(record),
                "answer_score": answer_score,
                "retrieval_score": retrieval_score,
            }
        )
    return sorted(
        scored,
        key=lambda item: (
            int(item["token_budget"]),
            str(item["case_id"]),
            str(item["method_id"]),
        ),
    )


def summarize_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate quality and online efficiency for each arm and token budget."""

    grouped: defaultdict[tuple[str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(str(record["method_id"]), int(record["token_budget"]))].append(record)
    summaries: dict[str, Any] = {}
    for method_id in METHODS:
        summaries[method_id] = {}
        for budget in BUDGETS:
            cells = grouped[(method_id, budget)]
            if len(cells) != 10:
                raise DG16LME10Error("summary cell denominator drifted")
            exact = [float(cell["answer_score"]["exact_match"]) for cell in cells]
            f1 = [float(cell["answer_score"]["normalized_f1"]) for cell in cells]
            hit = [float(cell["retrieval_score"]["hit_at_k"]) for cell in cells]
            coverage = [
                float(cell["retrieval_score"]["relevant_coverage_at_k"])
                for cell in cells
            ]
            query = [float(cell["query_latency_ms"]) for cell in cells]
            provider = [
                float(cell["provider"]["provider_latency_ms"]) for cell in cells
            ]
            tokenize = [
                float(cell["provider"]["tokenize_latency_ms"]) for cell in cells
            ]
            answer_path = [
                query_ms + tokenize_ms + provider_ms
                for query_ms, tokenize_ms, provider_ms in zip(
                    query, tokenize, provider, strict=True
                )
            ]
            context_tokens = [float(cell["context_tokens"]) for cell in cells]
            prompt_tokens = [float(cell["provider"]["prompt_tokens"]) for cell in cells]
            completion_tokens = [
                float(cell["provider"]["completion_tokens"]) for cell in cells
            ]
            summaries[method_id][str(budget)] = {
                "case_count": len(cells),
                "exact_match_count": int(sum(exact)),
                "exact_match": round(mean(exact), 9),
                "normalized_f1": round(mean(f1), 9),
                "retrieval_hit_at_k": round(mean(hit), 9),
                "evidence_session_recall": round(mean(coverage), 9),
                "query_latency_ms": {
                    "mean": round(mean(query), 6),
                    "p50": round(median(query), 6),
                    "p95": round(_percentile(query, 0.95), 6),
                },
                "provider_latency_ms": {
                    "mean": round(mean(provider), 6),
                    "p50": round(median(provider), 6),
                    "p95": round(_percentile(provider, 0.95), 6),
                },
                "answer_path_latency_ms": {
                    "definition": "query + provider_tokenize + provider_generation",
                    "mean": round(mean(answer_path), 6),
                    "p50": round(median(answer_path), 6),
                    "p95": round(_percentile(answer_path, 0.95), 6),
                },
                "context_tokens_mean": round(mean(context_tokens), 3),
                "prompt_tokens_mean": round(mean(prompt_tokens), 3),
                "completion_tokens_mean": round(mean(completion_tokens), 3),
                "provider_calls": sum(
                    int(cell["provider"]["provider_calls"]) for cell in cells
                ),
                "retrieval_logical_calls": sum(
                    int(cell["usage"].get("retrieval_logical_calls", 0))
                    for cell in cells
                ),
                "automatic_retries": 0,
            }
    return summaries


def summarize_lifecycle(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate shared per-case lifecycle costs separately from online latency."""

    grouped: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["method_id"])].append(record)
    result: dict[str, Any] = {}
    for method_id in METHODS:
        cases = grouped[method_id]
        if len(cases) != 10:
            raise DG16LME10Error("lifecycle case denominator drifted")

        def values(
            field: str, selected_cases: Sequence[Mapping[str, Any]] = cases
        ) -> list[float]:
            return [float(case[field]) for case in selected_cases]

        totals = values("total_lifecycle_ms")
        total_ms = sum(totals)
        result[method_id] = {
            "case_count": len(cases),
            "event_count_total": sum(int(case["event_count"]) for case in cases),
            "runtime_start_ms_mean": round(mean(values("runtime_start_ms")), 6),
            "ingest_ms_mean": round(mean(values("ingest_ms")), 6),
            "finalize_ms_mean": round(mean(values("finalize_ms")), 6),
            "two_query_ms_mean": round(mean(values("query_ms")), 6),
            "cleanup_ms_mean": round(mean(values("cleanup_ms")), 6),
            "runtime_close_ms_mean": round(mean(values("runtime_close_ms")), 6),
            "full_lifecycle_ms": {
                "definition": "runtime_start + reset + ingest + finalize + two_queries + cleanup + runtime_close",
                "total": round(total_ms, 6),
                "mean_per_case": round(mean(totals), 6),
                "p50_per_case": round(median(totals), 6),
                "p95_per_case": round(_percentile(totals, 0.95), 6),
                "amortized_per_answer_cell": round(total_ms / 20, 6),
            },
            "sequential_cases_per_hour": round(3_600_000 / mean(totals), 3),
            "logical_mcp_calls_total": sum(
                int(case["logical_mcp_calls"]) for case in cases
            ),
            "physical_mcp_batches_total": sum(
                int(case["physical_mcp_batches"]) for case in cases
            ),
        }
    return result


def compare_summaries(
    summaries: Mapping[str, Mapping[str, Mapping[str, Any]]],
    lifecycle: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Compute MiLA-minus-BM25 quality deltas and explicit latency ratios."""

    comparison: dict[str, Any] = {"by_budget": {}}
    for budget in BUDGETS:
        milai = summaries["DG16-MILAI-MCP"][str(budget)]
        bm25 = summaries["LME-BM25-T"][str(budget)]
        comparison["by_budget"][str(budget)] = {
            "exact_match_delta": round(
                float(milai["exact_match"]) - float(bm25["exact_match"]), 9
            ),
            "normalized_f1_delta": round(
                float(milai["normalized_f1"]) - float(bm25["normalized_f1"]), 9
            ),
            "evidence_session_recall_delta": round(
                float(milai["evidence_session_recall"])
                - float(bm25["evidence_session_recall"]),
                9,
            ),
            "answer_path_latency_ratio_milai_over_bm25": round(
                float(milai["answer_path_latency_ms"]["mean"])
                / float(bm25["answer_path_latency_ms"]["mean"]),
                6,
            ),
            "query_latency_ratio_milai_over_bm25": round(
                float(milai["query_latency_ms"]["mean"])
                / float(bm25["query_latency_ms"]["mean"]),
                6,
            ),
        }
    milai_lifecycle = float(
        lifecycle["DG16-MILAI-MCP"]["full_lifecycle_ms"]["mean_per_case"]
    )
    bm25_lifecycle = float(
        lifecycle["LME-BM25-T"]["full_lifecycle_ms"]["mean_per_case"]
    )
    comparison["full_lifecycle_ratio_milai_over_bm25"] = round(
        milai_lifecycle / bm25_lifecycle, 6
    )
    return comparison


__all__ = [
    "BUDGETS",
    "EXPECTED_LABEL_SOURCE_SHA256",
    "LABEL_SOURCE",
    "METHODS",
    "DG16LME10Error",
    "compare_summaries",
    "load_public_dev_cases",
    "load_public_dev_labels",
    "score_records",
    "sha256_file",
    "summarize_lifecycle",
    "summarize_records",
]
