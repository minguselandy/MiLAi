"""Summarize closed Reader receipts, standalone selection costs and paired families.

Native scores remain unchanged. Source fidelity needs separate author review;
reference-support inclusion is only a mechanical coverage measure.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from milai_lab.harness.artifact_io import read_json, write_json
from run_bounded_reader_selection import read_rows
from run_musique_reader import reader_input


def family_difference(rows, baseline, candidate):
    groups = defaultdict(list)
    for row in rows:
        if row["answerable"]:
            groups[row["family"]].append(row["arms"][candidate]["f1"]
                                         - row["arms"][baseline]["f1"])
    differences = {family: mean(values) for family, values in sorted(groups.items())}
    values = list(differences.values())
    generator = random.Random(20261017)  # noqa: S311 -- statistical resampling
    estimates = sorted(mean(generator.choices(values, k=len(values))) for _ in range(10000))

    def quantile(probability):
        position = probability * (len(estimates) - 1)
        low, high = math.floor(position), math.ceil(position)
        return estimates[low] + (estimates[high] - estimates[low]) * (position - low)

    return {"baseline": baseline, "candidate": candidate, "families": len(values),
            "mean_difference": mean(values),
            "percentile_95_interval": [quantile(.025), quantile(.975)],
            "replicates": 10000, "seed": 20261017, "family_differences": differences,
            "scope": "Conditional on these exposed development families and first responses; "
                     "not independent test inference or repeated-generation uncertainty."}


def summarize(root):
    protocol = read_json(root / "dispatch.json")
    predictions = root / "reader-v1"
    run = read_json(predictions / "run.json")
    if run["status"] != "COMPLETED":
        raise ValueError("Review requires all first predictions to be terminal")
    scores = read_json(root / "score-v1/results.json")["arms"]
    cases = {row["case_id"]: row for row in read_rows(Path(protocol["cases"]))}
    labels = read_rows(Path(protocol["labels"]))
    sys.path.insert(0, protocol["official_scorer"])
    from metrics.answer import AnswerMetric

    retrieval = read_json(Path(protocol["common_retrieval_costs"]))
    retrieval_wall = sum(row["wall_seconds"] for row in retrieval)
    receipts = {str(path.parent.relative_to(predictions / "http")): read_json(path)
                for path in (predictions / "http").rglob("response.json")}
    actual = Counter()
    for response in receipts.values():
        actual.update({key: response["usage"][key]
                      for key in ("prompt_tokens", "completion_tokens", "total_tokens")})
    actual["generation_responses"] = len(receipts)
    start, end = (read_json(predictions / name) for name in
                  ("accounting-start.json", "accounting-end.json"))
    audit = {"generation_token_difference": end["generation"]["known_tokens"]
             - start["generation"]["known_tokens"] - actual["total_tokens"],
             "generation_request_difference": end["generation_requests"]
             - start["generation_requests"] - len(receipts),
             "embedding_token_delta": end["embedding"]["known_tokens"]
             - start["embedding"]["known_tokens"]}
    for kind in ("generation", "embedding"):
        audit[kind + "_new_unknown"] = end[kind]["unknown_usage"] - start[kind]["unknown_usage"]
    arms, comparisons, format_issues = {}, [], []
    verified = 0
    for arm, config in protocol["arms"].items():
        cost, opens, stops = Counter(), Counter(), Counter()
        seen, within_arm_cache_savings = set(), Counter()
        for row in labels:
            cid = row["case_id"]
            selection = read_json(Path(config["selection_root"]) / cid
                                  / (config["policy"] + ".json"))
            result = read_json(predictions / "predictions" / arm / (cid + ".json"))
            key = result["reader_call_key"]
            request = read_json(predictions / "http" / key / "request.json")
            messages, schema = reader_input(cases[cid], selection["selected_ids"])
            if request["messages"] != messages or request["response_format"] != schema:
                raise ValueError(f"Actual Reader input differs: {arm}/{cid}")
            verified += 1
            usage = receipts[key]["usage"]
            if key in seen:
                for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    within_arm_cache_savings["reader_" + name] += usage[name]
                within_arm_cache_savings["reader_first_call_wall_seconds"] += result["wall_seconds"]
            seen.add(key)
            for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                cost["reader_" + name] += usage[name]
            cost["reader_first_call_wall_seconds"] += result["wall_seconds"]
            cost["reader_positions"] += 1
            cost["fresh_reader_calls"] += not result["reused_reader_output"]
            cost["reused_reader_outputs"] += result["reused_reader_output"]
            cost["controller_input_tokens"] += selection.get("standalone_model_input_tokens", 0)
            cost["controller_model_wall_seconds"] += selection.get(
                "standalone_model_wall_seconds", 0)
            cost["controller_decision_positions"] += selection["decision_calls"]
            cost["opened_documents"] += len(selection["selected_ids"])
            opens[len(selection["selected_ids"])] += 1
            stops[selection["stop_reason"]] += 1
            answer = result["answer"]
            if answer is not None and not answer["answerable"] and answer["answer"]:
                format_issues.append({"arm": arm, "case": cid, "answer": answer,
                                      "issue": "insufficient_evidence_requires_empty_answer"})
        cost["common_retrieval_wall_seconds"] = retrieval_wall
        per_position = dict(cost)
        for key, value in within_arm_cache_savings.items():
            cost[key] -= value
        cost["standalone_unique_reader_calls"] = len(seen)
        cost["reader_plus_controller_input_tokens"] = (
            cost["reader_prompt_tokens"] + cost["controller_input_tokens"])
        cost["reader_plus_controller_total_tokens"] = (
            cost["reader_total_tokens"] + cost["controller_input_tokens"])
        cost["warm_component_wall_sum_seconds"] = (cost["reader_first_call_wall_seconds"]
            + cost["controller_model_wall_seconds"] + retrieval_wall)
        arms[arm] = {"native": {k: v for k, v in scores[arm].items() if k != "observations"},
                     "standalone_cost": dict(cost), "per_position_cost": per_position,
                     "opened_count_histogram": dict(opens),
                     "stop_reasons": dict(stops)}
    for row in labels:
        source, cid = row["source"], row["case_id"]
        comparison = {"id": cid, "family": row["family"],
                      "answerable": source["answerable"], "arms": {}}
        for arm in arms:
            observed = scores[arm]["observations"][cid]
            metric = AnswerMetric()
            answer = observed.get("prediction", {}).get("predicted_answer", "")
            metric(answer, [source["answer"], *source["answer_aliases"]])
            comparison["arms"][arm] = {"answer": answer, "f1": metric.get_metric()[1]
                if source["answerable"] else None,
                "reference_support_delivered": observed.get("reference_support_delivered", False)}
        comparisons.append(comparison)
    return {"status": "CLOSED_RECEIPTS_AND_NATIVE_SCORES_RECONCILED", "run": run,
            "source_version": protocol["execution_source_version"], "arms": arms,
            "actual_reader_usage": dict(actual), "ledger_differences": audit,
            "literal_reader_inputs_verified": verified, "semantic_format_issues": format_issues,
            "paired_positive_families": [family_difference(comparisons, other, "laya_ce_k4")
                for other in ("bm25_k4", "laya_ce_adaptive")],
            "case_comparisons": comparisons,
            "cost_scope": "Standalone costs include reused first responses and cached controller "
                "forwards; identical Reader inputs within each arm are charged once. "
                "Gross per-position costs are separate. "
                "Actual ledger charges each shared call once. "
                "Encoder input tokens and Reader generated tokens are distinct workloads. "
                "Warm component sum excludes cold load and unmeasured orchestration/review costs; "
                "it is not measured standalone end-to-end latency."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    write_json(args.output, summarize(args.root))


if __name__ == "__main__":
    main()
