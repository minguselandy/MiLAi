"""Summarize saved paired predictions, first labels and original cost receipts only."""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any

from milai_lab.runners.method_architecture_diagnostic import diagnostic_costs


def read(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(path.read_text())
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--state-review", type=Path)
    args = parser.parse_args()
    driver = read(args.run / "driver.json")
    settings = read(args.run / "plain.json")["entrypoints"]["benchmark"]
    conditions = {}
    for arm in ("plain", "delta"):
        root = args.run / arm / "MiLAi-memory-only"
        score = read(root / "common-qa-results.json")
        costs = diagnostic_costs(root)
        conditions[arm] = {"first_qa": {key: score[key] for key in (
            "correct", "opportunities", "missing", "labels", "per_user")}, "costs": costs,
            "prediction_generation_tokens": sum(cost["known_tokens"]
                for name, cost in costs["stages"].items() if name not in {"embedding", "judge"}),
            "prediction_terminal": read(root / "terminal-predict.json")["status"],
            "score_terminal": read(root / "terminal-score.json")["status"]}
    before, after = [read(args.run / f"accounting-{suffix}.json") for suffix in ("start", "end")]
    ledger = {kind: {field: after[kind][field] - before[kind][field]
                    for field in ("known_tokens", "charged_tokens", "unknown_usage")}
              for kind in ("generation", "embedding")}
    ledger["generation"]["requests"] = after["generation_requests"] - before["generation_requests"]
    receipts = {"generation": {"tokens": 0, "responses": 0},
                "embedding": {"tokens": 0, "responses": 0}}
    for condition in conditions.values():
        for name, cost in condition["costs"]["stages"].items():
            key = "embedding" if name == "embedding" else "generation"
            receipts[key]["tokens"] += cost["known_tokens"]
            receipts[key]["responses"] += cost["responses"]
    users = list(conditions["plain"]["first_qa"]["per_user"])
    differences = []
    for user in users:
        plain, delta = [conditions[arm]["first_qa"]["per_user"][user]
                        for arm in ("plain", "delta")]
        differences.append(delta["correct"] / delta["opportunities"]
                           - plain["correct"] / plain["opportunities"])
    # This diagnostic has six independent chains. Enumerating all cluster
    # resamples avoids a seed-selection story and preserves within-chain pairing.
    samples = sorted(sum(sample) / len(users)
                     for sample in itertools.product(differences, repeat=len(users)))
    interval = [samples[int(q * (len(samples) - 1))] for q in (0.025, 0.975)]
    summary = {
        "status": driver["status"], "source_version": driver["source_version"],
        "models": {"generation": settings["model"]["model"],
                   "embedding": settings["embedding"]["model"],
                   "context_tokens": settings["context_tokens"],
                   "output_ceiling": settings["model"]["max_tokens"]},
        "stage_wall_seconds": {f"{step['arm']}/{step['phase']}":
                               step["finished_at"] - step["started_at"]
                               for step in driver["steps"]},
        "latency_scope": "Whole CLI stage on the existing shared local services, including IO "
                         "and embeddings; not pure GPU time or a controlled speedup claim.",
        "monetary_cost": None,
        "conditions": conditions, "ledger_delta": ledger, "receipt_totals": receipts,
        "ledger_minus_receipts": {kind: ledger[kind]["known_tokens"] - receipts[kind]["tokens"]
                                  for kind in receipts},
        "exploratory_paired_qa": {"clusters": len(users), "unit": "source history chain",
            "per_chain_rate_difference": dict(zip(users, differences, strict=True)),
            "mean_difference": sum(differences) / len(users), "percentile_95_interval": interval,
            "all_cluster_resamples": len(samples),
            "invalids": "Retained separately; not correct in the all-opportunity denominator.",
            "limitations": "Author development histories; same-family first Judge; "
                           "source/reference ambiguities remain. Not a noninferiority test "
                           "or independent confirmation."},
        "source_reviews": ["innovation-v4-paired-v2-plain-review.json",
                           "innovation-v4-paired-v2-delta-review.json"],
        "source_author_issues": "Weekend/date ambiguity and catalog independence versus uptime "
                                "are retained in both methods; original first labels unchanged.",
        "state_result": "Mixed positives and failures; raw-source QA does not prove state success. "
                        "Full structured source/scope joint audit remains pending.",
        "decision": "Current delta is not a demonstrated quality-cost advantage: prediction "
                    "tokens increase and joint state correctness is unproven. Continue query-local "
                    "allocation and matched learning; no failed-call replay "
                    "or selective rejudging.",
        "official_benchmark_claim": False, "parameter_training_completed": False,
    }
    if args.state_review is not None:
        review = read(args.state_review)
        summary["source_reviews"].append(args.state_review.name)
        summary["author_transition_joint"] = review["counts"]
        summary["state_result"] = (
            "Structured states and literal bindings author-reviewed; see attached coverage. "
            "Joint transition count bounds reflect ambiguous labels, not confidence "
            "intervals or full-history success. Inherited omissions and absent historical "
            "states remain. Source identities/ranges valid does not mean semantic support. "
            "This post-hoc author review is not independent blind confirmation."
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": summary["status"], "receipt_totals": receipts,
                      "ledger_minus_receipts": summary["ledger_minus_receipts"],
                      "qa_difference": summary["exploratory_paired_qa"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
