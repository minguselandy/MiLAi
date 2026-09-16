from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from milai.adapters.agent_prefetch import prepare_compact_prefetch
from milai.application.retrieval import _weighted_set_cover_select

from evals.benchmark import dg11_measurement
from evals.benchmark import lme_product_smoke as benchmark
from scripts import dg11_state

INPUTS = ROOT / "var/dg11/holdout/v1/holdout-inputs.json"
DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")


def _compile(case: dict[str, Any], selected: list[dict[str, Any]]) -> str:
    context = prepare_compact_prefetch(
        {
            "status": "OK",
            "items": [
                {
                    "memory_text": item["memory_text"],
                    "payload": {"session_id": item["session_id"]},
                    "valid_time_from": item["valid_time_from"],
                    "relevance_score": item["relevance_score"],
                    "authority": "ACTION_SAFE",
                    "epistemic_status": "VERIFIED",
                }
                for item in selected
            ],
            "open_issue_ids": [],
            "degraded_components": [],
            "abstention_reason": None,
        },
        query=case["question"],
        max_context_chars=benchmark.COMPACT_CONTEXT_CHARS,
    )
    return context.rendered


def run(run_id: str, pool_run: Path) -> dict[str, Any]:
    run_dir = ROOT / "var/dg11/runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    input_payload = json.loads(INPUTS.read_text(encoding="utf-8"))
    cases = {case["source_id"]: case for case in input_payload["cases"]}
    pool_result = json.loads((pool_run / "result.json").read_text(encoding="utf-8"))
    pool_summary = pool_result.get("summary")
    if (
        pool_result.get("status") != "PASS"
        or not isinstance(pool_summary, dict)
        or pool_summary.get("empty_pool_count") != 0
        or pool_summary.get("recall_transports") != ["AUTHORIZED_HTTP_RETRIEVAL"]
    ):
        raise RuntimeError("R02 offline A/B requires a valid authorized HTTP candidate pool")
    pool_payload = json.loads(
        (pool_run / "candidate-pool-contexts.json").read_text(encoding="utf-8")
    )
    pool_records = {record["source_id"]: record for record in pool_payload["records"]}
    rows = {
        row["question_id"]: row
        for row in json.loads(DATASET.read_text(encoding="utf-8"))
        if row.get("question_id") in pool_records
    }
    tokenizer = Tokenizer.from_file(str(TOKENIZER))
    variants = {"B0_TOP3": None, "B2_SET_COVER": 0.14, "B4_SET_COVER_MMR": 0.28}
    records: list[dict[str, Any]] = []
    for source_id, pool_record in pool_records.items():
        case = cases[source_id]
        sessions = {session["session_id"]: session for session in case["sessions"]}
        candidates = [
            {
                **item,
                "memory_text": sessions[item["session_id"]]["text"],
                "payload": {
                    "session_id": item["session_id"],
                    "memory_text": sessions[item["session_id"]]["text"],
                },
            }
            for item in pool_record["trace"]["retrieved_items"]
        ]
        relevant = {str(value) for value in rows[source_id]["answer_session_ids"]}
        answers = benchmark.scoring._answer_values(rows[source_id]["answer"])
        for variant, diversity_weight in variants.items():
            selected = (
                candidates[:3]
                if diversity_weight is None
                else _weighted_set_cover_select(
                    candidates,
                    3,
                    query=case["question"],
                    diversity_weight=diversity_weight,
                )
            )
            selected_ids = [str(item["session_id"]) for item in selected]
            hits = relevant.intersection(selected_ids)
            rendered = _compile(case, selected)
            records.append(
                {
                    "source_id": source_id,
                    "variant": variant,
                    "selected_session_ids": selected_ids,
                    "retrieval_hit_at_3": int(bool(hits)),
                    "relevant_coverage_at_3": round(len(hits) / len(relevant), 6),
                    "answer_span_present": dg11_measurement.answer_span_present(
                        rendered, answers
                    ),
                    "memory_tokens": len(tokenizer.encode(rendered).ids),
                }
            )
    aggregates: dict[str, Any] = {}
    for variant in variants:
        group = [record for record in records if record["variant"] == variant]
        hits = [record for record in group if record["retrieval_hit_at_3"] == 1]
        aggregates[variant] = {
            "case_count": len(group),
            "retrieval_hit_at_3": round(
                mean(record["retrieval_hit_at_3"] for record in group), 6
            ),
            "relevant_coverage_at_3": round(
                mean(record["relevant_coverage_at_3"] for record in group), 6
            ),
            "answer_span_survival_on_hit": (
                round(mean(record["answer_span_present"] for record in hits), 6)
                if hits
                else 0.0
            ),
            "answer_span_present_rate": round(
                mean(record["answer_span_present"] for record in group), 6
            ),
            "memory_tokens_mean": round(
                mean(record["memory_tokens"] for record in group), 3
            ),
            "memory_tokens_max": max(record["memory_tokens"] for record in group),
            "selection_changed_vs_b0": sum(
                record["selected_session_ids"]
                != next(
                    baseline["selected_session_ids"]
                    for baseline in records
                    if baseline["source_id"] == record["source_id"]
                    and baseline["variant"] == "B0_TOP3"
                )
                for record in group
            ),
        }
    baseline = aggregates["B0_TOP3"]
    eligible = [
        variant
        for variant in ("B2_SET_COVER", "B4_SET_COVER_MMR")
        if aggregates[variant]["relevant_coverage_at_3"]
        > baseline["relevant_coverage_at_3"]
        and aggregates[variant]["answer_span_present_rate"]
        > baseline["answer_span_present_rate"]
        and aggregates[variant]["memory_tokens_max"] <= 512
    ]
    selected_variant = max(
        eligible,
        key=lambda variant: (
            aggregates[variant]["answer_span_present_rate"],
            aggregates[variant]["relevant_coverage_at_3"],
        ),
        default=None,
    )
    result = {
        "schema": "milai.dg11.r02-offline-ab.v1",
        "run_id": run_id,
        "work_package": "DG11-R02",
        "status": "PASS" if selected_variant else "REVISE",
        "decision": (
            f"KEEP_{selected_variant}" if selected_variant else "REVISE_SELECTION"
        ),
        "selected_variant": selected_variant,
        "provider_requests": 0,
        "hidden_provider_calls": 0,
        "development_ai_reviews": 0,
        "aggregates": aggregates,
        "records": records,
    }
    dg11_state.atomic_json(run_dir / "result.json", result)
    dg11_state.append_ledger(
        {
            "run_id": run_id,
            "work_package": "DG11-R02",
            "status": result["status"],
            "decision": result["decision"],
            "provider_requests": 0,
            "development_ai_reviews": 0,
            "metrics": aggregates,
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--pool-run", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.run_id, args.pool_run.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
