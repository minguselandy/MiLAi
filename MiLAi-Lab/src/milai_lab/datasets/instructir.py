"""InstructIR public requests and the released query-group robustness protocol."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
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


def delivered_document_ranking(
    packet: dict[str, Any], resolve_material: Callable[[dict[str, Any]], dict[str, Any]],
    source_to_document: dict[str, str],
) -> dict[str, Any]:
    """Rank only sources selected in the actual returned packet, in wire order.

    Every corpus document has its own source/session. An original range selects
    that document. A delivered interpretation selects only its explicit node
    citations, not every binding retained in the view or every search candidate.
    Citation-based retrieval does not claim the original text reached the Reader.
    """
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    def select(source: str, ref: dict[str, Any], basis: str, **details: Any) -> None:
        document = source_to_document[source]
        if document not in seen:
            seen.add(document)
            entries.append({"document_id": document, "source_ref": source,
                            "material_ref": ref, "basis": basis, **details})

    for item in packet["evidence"]:
        if item["kind"] == "original_source":
            if not item.get("evidence"):
                continue
            material = resolve_material(item["ref"])
            refs = {span["source_ref"] for span in material["source_ranges"]}
            if len(refs) != 1:
                raise ValueError("InstructIR requires one corpus document per source pack")
            ranges = [[span["start"], span["end"]] for span in material["source_ranges"]]
            if ranges != [turn["range"] for turn in item["evidence"]]:
                raise ValueError("Delivered source ranges differ from the retained material")
            select(next(iter(refs)), item["ref"], "delivered_original_range", ranges=ranges)
        elif item["kind"] == "query_structure":
            if "interpretation" not in item:
                continue
            material = resolve_material(item["ref"])
            for node_id, node in item["interpretation"]["nodes"].items():
                for alias in node["evidence"]:
                    select(material["source_bindings"][alias]["source_ref"], item["ref"],
                           "delivered_interpretation_citation", node=node_id, citation=alias)
        else:
            raise ValueError("Unsupported returned material for the declared InstructIR projection")
    return {"ranking": {row["document_id"]: 1.0 / (i + 1) for i, row in enumerate(entries)},
            "entries": entries,
            "ordering": "First occurrence in actual ToolMessage material/node/citation order; "
                        "reciprocal rank values encode order only, not similarity/confidence.",
            "scope": "Delivered original ranges or explicit delivered interpretation citations. "
                     "No unreturned candidates, unused view bindings, qrels or answer fields."}


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
