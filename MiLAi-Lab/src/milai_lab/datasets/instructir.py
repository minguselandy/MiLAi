"""InstructIR public requests and the released query-group robustness protocol."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def retrieval_request(row: dict[str, Any]) -> dict[str, Any]:
    """Match the author's instruction[SEP]query parsing; no IDs or qrels online."""
    instruction, query = row["text"].split("[SEP]")
    return {"query": query.strip(), "read_goal": {"purpose": instruction.strip()}}


def corpus_sources(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Keep full title/text, with corpus IDs only in the offline receipt mapping."""
    return [{"session_id": f"instructir-document-{index}", "event_key": "document",
             "original_event_id": row["_id"], "role": "tool", "origin": "reference_document",
             "occurred_at": None, "content": row["title"] + "\n" + row["text"]}
            for index, row in enumerate(rows)]


def evaluate_rankings(
    queries: list[dict[str, Any]], qrels: dict[str, dict[str, int]],
    results: dict[str, dict[str, float]], *,
    cutoffs: tuple[int, ...] = (1, 3, 5, 10, 100, 1000),
    ignore_identical_ids: bool = True,
) -> dict[str, Any]:
    """Use pytrec_eval, then reproduce the author's per-original-query minimum.

    Normal scores average all instruction instances. Robust scores average the
    worst instruction score within each original query. Missing runs are explicit
    zeros in the complete cohort, not silently removed from either denominator.
    No actual prediction or qrel is modified in place.
    """
    import pytrec_eval  # type: ignore[import-not-found]

    ids = [row["_id"] for row in queries]
    cohort = set(ids)
    if set(results) - cohort:
        raise ValueError("Ranking contains a query outside the declared cohort")
    if cohort - set(qrels):
        raise ValueError("Every declared query needs its released qrels")
    runs = {qid: {doc: float(score) for doc, score in results.get(qid, {}).items()
                  if not ignore_identical_ids or doc != qid} for qid in ids}
    measures = {name + "." + ",".join(map(str, cutoffs))
                for name in ("ndcg_cut", "map_cut", "recall", "P")}
    evaluated = pytrec_eval.RelevanceEvaluator(qrels, measures).evaluate(runs)
    groups: dict[str, list[str]] = defaultdict(list)
    for row in queries:
        groups[retrieval_request(row)["query"]].append(row["_id"])
    names = {"NDCG": "ndcg_cut", "MAP": "map_cut", "Recall": "recall", "P": "P"}
    metrics: dict[str, float] = {}
    for display, native in names.items():
        for k in cutoffs:
            key = f"{native}_{k}"
            values = {qid: float(evaluated[qid][key]) for qid in ids}
            metrics[f"cluster_{display}@{k}_avg"] = sum(values.values()) / len(values)
            worst = [min(values[qid] for qid in members) for members in groups.values()]
            metrics[f"cluster_{display}@{k}_min_avg"] = sum(worst) / len(worst)
    return {"metrics": metrics, "queries": len(queries), "query_groups": len(groups),
            "missing_rankings": sorted(cohort - set(results)),
            "empty_rankings": sum(not values for values in runs.values()),
            "per_query": evaluated,
            "scope": "Released pytrec_eval metric families and original-query grouping; "
                     "complete-cohort denominator includes missing/empty rankings. "
                     "This scoring utility does not establish model coverage or performance."}
