from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import mean
from typing import Any

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.benchmark import dg11_measurement
from evals.benchmark import lme_product_smoke as benchmark
from evals.benchmark.dg11_cross_encoder import FrozenOnnxCrossEncoder, blend_scores
from scripts import dg11_state
from scripts.run_dg11_r02_offline_ab import _compile

INPUTS = ROOT / "var/dg11/holdout/v1/holdout-inputs.json"
DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
MODEL_ROOT = ROOT / "runtime/var/models/ms-marco-MiniLM-L6-v2-cross-encoder"
MODEL_ID = "cross-encoder/ms-marco-MiniLM-L6-v2"
MODEL_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
VARIANTS = {
    "B0_TOP3": None,
    "B3_CROSS_ENCODER_100": 1.0,
    "B3_CROSS_ENCODER_80": 0.8,
    "B3_CROSS_ENCODER_60": 0.6,
}


def run(run_id: str, pool_run: Path) -> dict[str, Any]:
    run_dir = ROOT / "var/dg11/runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    pool_result = json.loads((pool_run / "result.json").read_text(encoding="utf-8"))
    if (
        pool_result.get("status") != "PASS"
        or pool_result.get("summary", {}).get("empty_pool_count") != 0
    ):
        raise RuntimeError("B3 requires a complete canonical-gated candidate pool")
    input_payload = json.loads(INPUTS.read_text(encoding="utf-8"))
    cases = {case["source_id"]: case for case in input_payload["cases"]}
    pool_payload = json.loads(
        (pool_run / "candidate-pool-contexts.json").read_text(encoding="utf-8")
    )
    pool_records = {record["source_id"]: record for record in pool_payload["records"]}
    rows = {
        row["question_id"]: row
        for row in json.loads(DATASET.read_text(encoding="utf-8"))
        if row.get("question_id") in pool_records
    }
    target_tokenizer = Tokenizer.from_file(str(TOKENIZER))
    reranker = FrozenOnnxCrossEncoder(
        MODEL_ROOT, model_id=MODEL_ID, revision=MODEL_REVISION
    )
    inference_durations: list[float] = []
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
        started = time.perf_counter()
        cross_scores = reranker.score(
            case["question"], [item["memory_text"] for item in candidates]
        )
        inference_durations.append((time.perf_counter() - started) * 1000)
        retrieval_scores = [float(item["relevance_score"]) for item in candidates]
        relevant = {str(value) for value in rows[source_id]["answer_session_ids"]}
        answers = benchmark.scoring._answer_values(rows[source_id]["answer"])
        for variant, cross_weight in VARIANTS.items():
            if cross_weight is None:
                selected = candidates[:3]
            else:
                blended = blend_scores(
                    cross_scores,
                    retrieval_scores,
                    cross_encoder_weight=cross_weight,
                )
                selected = [
                    candidates[index]
                    for index in sorted(
                        range(len(candidates)),
                        key=lambda index: (blended[index], -index),
                        reverse=True,
                    )[:3]
                ]
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
                    "memory_tokens": len(target_tokenizer.encode(rendered).ids),
                }
            )
    aggregates: dict[str, Any] = {}
    for variant in VARIANTS:
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
        }
    baseline = aggregates["B0_TOP3"]
    eligible = [
        variant
        for variant in VARIANTS
        if variant != "B0_TOP3"
        and aggregates[variant]["relevant_coverage_at_3"]
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
        "schema": "milai.dg11.r02-crossencoder-ab.v1",
        "run_id": run_id,
        "work_package": "DG11-R02",
        "status": "PASS" if selected_variant else "REVISE",
        "decision": (
            f"KEEP_{selected_variant}" if selected_variant else "STOP_B3_NO_CROSS_SLICE_GAIN"
        ),
        "selected_variant": selected_variant,
        "provider_requests": 0,
        "hidden_provider_calls": 0,
        "local_reranker": {
            **reranker.identity,
            "inference_batches": reranker.inference_batches,
            "scored_pairs": reranker.scored_pairs,
            "latency_ms_mean": round(mean(inference_durations), 3),
            "latency_ms_max": round(max(inference_durations), 3),
        },
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
            "metrics": {
                "selected_variant": selected_variant,
                "aggregates": aggregates,
                "local_reranker": result["local_reranker"],
            },
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
