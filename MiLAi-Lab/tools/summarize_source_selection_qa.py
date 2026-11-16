"""Summarize both frozen fixed4 cohorts, retaining source qualifications and all seeds."""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from join_global_reader_review import verdict
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from summarize_global_reader_cohorts import summarize
from summarize_musique_reader import family_difference


def natural_pairs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["dataset"] + ":" + row["question_id"]].append(row)
    native, source = [], []
    for question, group in groups.items():
        if len(group) != 2:
            continue
        if {r["native_positive"] for r in group} == {False, True}:
            native.append({"question": question, "family": group[0]["family"],
                           "source_dispositions": [r["disposition"] for r in group]})
        if {r["disposition"] for r in group} == {"supported", "pool_insufficient"}:
            source.append({"question": question, "family": group[0]["family"],
                "both_source_task_pass": all(r["source_contract_task_pass"] for r in group),
                "source_qualified": any(r["source_qualified"] for r in group)})
    return {"native_positive_negative_pairs": len(native), "native_pair_details": native,
        "source_supported_insufficient_pairs": len(source),
        "both_source_task_pass": sum(p["both_source_task_pass"] for p in source),
        "unqualified_source_pairs": sum(not p["source_qualified"] for p in source),
        "source_pair_details": source,
        "scope": "Natural variants, not equivalent presentation. Original answerability does "
                 "not force a source-semantic polarity change; masked pairs remain excluded."}


def citation_sensitivity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply every pre-mapping citation supplement, preserving primary annotations."""
    alternative, affected = [], []
    for row in rows:
        annotation = row["annotation"]
        if "exploratory_citation_grounding" in annotation:
            amended = {**annotation,
                       "citation_grounding": annotation["exploratory_citation_grounding"]}
            result = verdict(amended, row["disposition"])
            alternative.append({**row, "annotation": amended, **result})
            affected.append({"case": row["case"], "response_id": row["response_id"],
                "supplement": annotation["exploratory_supplement"],
                "primary_task_pass": row["source_contract_task_pass"],
                "alternative_task_pass": result["source_contract_task_pass"],
                "primary_reader_pass": row["reader_response_pass"],
                "alternative_reader_pass": result["reader_response_pass"]})
        else:
            alternative.append(row)
    return {"affected_positions": affected, "all": summarize(alternative),
        "scope": "Exploratory citation routes logged before method mapping, applied to every "
                 "matching response in every arm. Primary annotations, source proofs, native "
                 "metrics, masking and contract requirements are unchanged."}


def collect(root: Path) -> dict[str, Any]:
    protocol = read_json(root / "protocol.json")
    semantic = read_json(root / "semantic-final/report.json")
    if semantic["status"] != "ALL_FIRST_RESPONSES_AUTHOR_REVIEWED_AND_JOINED":
        raise ValueError("Complete first-response review is required")
    labels = {r["case_id"]: r for r in
              (json.loads(line) for line in Path(protocol["labels"]).read_text().splitlines())}
    reviews = {r["source_row"]: r for r in read_json(Path(protocol["source_review"]))["cases"]}
    native = read_json(root / "score/results.json")["arms"]
    sys.path.insert(0, protocol["official_scorer"])
    from metrics.answer import AnswerMetric

    arms: dict[str, Any] = {}
    all_rows = {}
    for name, arm in semantic["arms"].items():
        output = []
        for item in arm["cases"]:
            label = labels[item["case"]]
            review = reviews[label["source_row"]]
            source = label["source"]
            observation = native[name]["observations"][item["case"]]
            metric = AnswerMetric()
            metric("" if observation["missing"] else observation["prediction"]["predicted_answer"],
                   [source["answer"], *source["answer_aliases"]])
            output.append({**item, "question_id": source["id"], "dataset": label["dataset"],
                "native_positive": source["answerable"], "native_f1": metric.get_metric()[1],
                "source_qualified": review.get("qualified", False),
                "minimum_proof_reads": min(map(len, review["complete_proofs"]))
                                       if review["complete_proofs"] else None,
                "mechanism_tags": review["mechanism_tags"],
                "native_decomposition_steps": int(source["id"][0])
                                              if label["dataset"].startswith("musique") else None})
        all_rows[name] = {r["case"]: r for r in output}
        arms[name] = {"all": summarize(output),
            "exploratory_citation_sensitivity": citation_sensitivity(output),
            "by_dataset": {dataset: summarize([r for r in output if r["dataset"] == dataset])
                           for dataset in sorted({r["dataset"] for r in output})},
            "by_source_qualification": {str(flag): summarize([
                r for r in output
                if r["disposition"] == "supported" and r["source_qualified"] == flag])
                for flag in (False, True)},
            "by_minimum_proof_reads": {str(n): summarize([
                r for r in output if r["minimum_proof_reads"] == n]) for n in (1, 2, 3, 4)},
            "by_native_decomposition": {str(n): summarize([
                r for r in output if r["native_decomposition_steps"] == n]) for n in (2, 3, 4)},
            "by_family": {family: summarize([r for r in output if r["family"] == family])
                          for family in sorted({r["family"] for r in output})},
            "known_proof_delivery": {
                "eligible": sum(r["known_reviewed_proof_delivered"] is not None for r in output),
                "delivered": sum(r["known_reviewed_proof_delivered"] is True for r in output)},
            "natural_pairs": natural_pairs(output), "cases": output}
    comparisons = []
    difference: Callable[[list[dict[str, Any]], str, str], dict[str, Any]] = family_difference
    methods = [name for name in arms if name not in {"bm25_k4", "dense_k4", "full_pool"}]
    pairs = [(baseline, method) for method in methods for baseline in ("bm25_k4", "dense_k4")]
    pairs += [(f"reference_seed{seed}", f"source_seed{seed}") for seed in range(3)]
    for baseline, candidate in pairs:
        for stratum in ("supported", "supported_unqualified", "pool_insufficient", "native"):
            values = []
            for cid, left in all_rows[baseline].items():
                right = all_rows[candidate][cid]
                if stratum == "native":
                    include = left["native_positive"]
                elif stratum == "supported_unqualified":
                    include = left["disposition"] == "supported" and not left["source_qualified"]
                else:
                    include = left["disposition"] == stratum
                if include:
                    field = "native_f1" if stratum == "native" else "source_contract_task_pass"
                    values.append({"family": left["family"], "answerable": True,
                        "arms": {baseline: {"f1": float(left[field])},
                                 candidate: {"f1": float(right[field])}}})
            if values:
                comparison = difference(values, baseline, candidate)
                comparison.update(stratum=stratum, scope="Descriptive family bootstrap conditional "
                    "on this frozen cohort and first responses; not repeated-generation or "
                    "population uncertainty. Multiple comparisons, no seed selection.")
                comparisons.append(comparison)
    receipt = read_json(root / "receipt-review/report.json")
    return {"root": str(root), "arms": arms, "family_comparisons": comparisons,
        "actual_reader_usage_already_charged": receipt["actual_reader_usage"],
        "dense_cost_already_charged": receipt["dense_control"],
        "complete_cost_source": str(root / "receipt-review/report.json"),
        "native_metric_scope": protocol["native_metric_scope"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evaluation", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    report = {"status": "BOTH_SOURCE_SELECTION_COHORTS_ALL_SEEDS_REVIEWED_AND_SUMMARIZED",
        **{cohort: collect(args.evaluation / cohort) for cohort in ("dev", "reserved")},
        "new_model_calls": 0, "model_work_rebilled": False,
        "scope": "Source-qualified cases have separate denominators. Primary source success "
                 "is conditional on frozen assistant interpretations, not independent gold. "
                 "Native decomposition size and minimum proof reads are different variables."}
    write_json(args.output / "report.json", report)
    measures = {"wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu, "analyses": 1}
    path = Path(read_json(args.evaluation / "protocol.json")["budget"])
    with path.with_name("budget.json.http-owner.lock").open("a+b") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        budget = RunBudget(RunLimits(**read_json(path)["limits"]), path)
        budget.record_compute("source_selection_v2_cohort_summary", measures)
    write_json(args.output / "compute.json", measures)
    print(report["status"])


if __name__ == "__main__":
    main()
