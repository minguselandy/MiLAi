from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from milai.adapters.agent_prefetch import prepare_turn_window_prefetch

from evals.benchmark import dg11_measurement
from scripts import dg11_state
from scripts.run_dg10_benchmark_dev_smoke import _session_text

DEFAULT_RUN = ROOT / "var/dg10/runs/lme-dev-20260823-004"
DEFAULT_DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
DEFAULT_TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")


class TargetCounter:
    def __init__(self, path: Path) -> None:
        self._tokenizer = Tokenizer.from_file(str(path))

    def count_text(self, text: str) -> int:
        return len(self._tokenizer.encode(text).ids)


def _selected_rows(dataset: Path, selected: set[str]) -> dict[str, dict[str, Any]]:
    rows = json.loads(dataset.read_text(encoding="utf-8"))
    result = {
        str(row["question_id"]): row
        for row in rows
        if isinstance(row, dict) and row.get("question_id") in selected
    }
    if set(result) != selected:
        raise ValueError("DEV source rows are incomplete")
    return result


def _recall(row: dict[str, Any], retrieved_ids: list[str]) -> dict[str, Any]:
    session_ids = row["haystack_session_ids"]
    sessions = row["haystack_sessions"]
    dates = row["haystack_dates"]
    by_id = {
        str(session_id): (_session_text(session), str(date))
        for session_id, session, date in zip(session_ids, sessions, dates, strict=True)
    }
    items = []
    for rank, session_id in enumerate(retrieved_ids, start=1):
        text, observed_at = by_id[session_id]
        items.append(
            {
                "authority": "ACTION_SAFE",
                "epistemic_status": "VERIFIED",
                "relevance_score": 1.0 / rank,
                "valid_time_from": observed_at,
                "payload": {"session_id": session_id, "memory_text": text},
            }
        )
    return {
        "status": "OK",
        "items": items,
        "open_issue_ids": [],
        "degraded_components": [],
        "abstention_reason": None,
    }


def run(run_id: str, source_run: Path, dataset: Path, tokenizer_json: Path) -> dict[str, Any]:
    raw_path = source_run / "raw-records.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    records = [record for record in raw["records"] if record["arm"] == "MILAI_T3A"]
    if len(records) != 50:
        raise ValueError("compiler A/B requires 50 frozen MiLAi DEV records")
    source_ids = {str(record["case_id"]).removeprefix("longmemeval:") for record in records}
    rows = _selected_rows(dataset, source_ids)
    counter = TargetCounter(tokenizer_json)
    comparisons: list[dict[str, Any]] = []
    for record in records:
        source_id = str(record["case_id"]).removeprefix("longmemeval:")
        row = rows[source_id]
        answers = [str(answer) for answer in record["gold_answers"]]
        hit = float(record["retrieval_recall_at_k"]) == 1
        current = prepare_turn_window_prefetch(
            _recall(row, [str(value) for value in record["retrieved_session_ids"]]),
            query=str(record["question"]),
            max_context_chars=4_096,
            max_context_tokens=300,
            token_counter=counter,
        )
        comparisons.append(
            {
                "case_id": record["case_id"],
                "category": record["category"],
                "retrieval_hit_at_3": hit,
                "baseline_answer_span_present": dg11_measurement.answer_span_present(
                    str(record["memory_context"]), answers
                ),
                "current_answer_span_present": dg11_measurement.answer_span_present(
                    current.rendered, answers
                ),
                "baseline_context_tokens": counter.count_text(
                    str(record["memory_context"])
                ),
                "current_context_tokens": current.rendered_tokens,
                "compiler_version": current.compiler_version,
                "session_refs": list(current.session_refs),
            }
        )
    hit_records = [record for record in comparisons if record["retrieval_hit_at_3"]]
    baseline_survival = mean(
        float(record["baseline_answer_span_present"]) for record in hit_records
    )
    current_survival = mean(
        float(record["current_answer_span_present"]) for record in hit_records
    )
    current_tokens = [int(record["current_context_tokens"]) for record in comparisons]
    by_category: dict[str, dict[str, Any]] = {}
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in comparisons:
        grouped[str(record["category"])].append(record)
    for category, group in sorted(grouped.items()):
        hits = [record for record in group if record["retrieval_hit_at_3"]]
        by_category[category] = {
            "case_count": len(group),
            "hit_count": len(hits),
            "baseline_answer_span_survival_on_hit": round(
                mean(float(record["baseline_answer_span_present"]) for record in hits), 6
            )
            if hits
            else None,
            "current_answer_span_survival_on_hit": round(
                mean(float(record["current_answer_span_present"]) for record in hits), 6
            )
            if hits
            else None,
        }
    survival_delta = current_survival - baseline_survival
    gates = {
        "answer_span_survival_delta_gte_15pp": survival_delta >= 0.15,
        "mean_memory_tokens_lte_320": mean(current_tokens) <= 320,
        "max_memory_tokens_lte_512": max(current_tokens) <= 512,
        "denominator_50": len(comparisons) == 50,
        "provider_requests_zero": True,
    }
    status = "PASS" if all(gates.values()) else "REVISE"
    result = {
        "schema": "milai.dg11.compiler-offline-ab.v1",
        "run_id": run_id,
        "work_package": "DG11-01",
        "status": status,
        "decision": "KEEP_FOR_VLLM_AB" if status == "PASS" else "REVISE_COMPILER",
        "source_run_id": raw["run_id"],
        "source_raw_sha256": dg11_state.sha256(raw_path),
        "tokenizer_sha256": dg11_state.sha256(tokenizer_json),
        "summary": {
            "baseline_answer_span_survival_on_hit": round(baseline_survival, 6),
            "current_answer_span_survival_on_hit": round(current_survival, 6),
            "answer_span_survival_delta": round(survival_delta, 6),
            "current_memory_tokens_mean": round(mean(current_tokens), 3),
            "current_memory_tokens_max": max(current_tokens),
        },
        "category": by_category,
        "gates": gates,
        "records": comparisons,
        "provider_requests": 0,
        "development_ai_reviews": 0,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    dg11_state.record_result(
        result,
        phase="CONTEXT_FIXED" if status == "PASS" else "BASELINE_READY",
        work_package="DG11-01",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DG-11 compiler-only offline A/B")
    parser.add_argument("--run-id", default="dg11-compiler-offline-001")
    parser.add_argument("--source-run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--tokenizer-json", type=Path, default=DEFAULT_TOKENIZER)
    args = parser.parse_args()
    result = run(
        args.run_id,
        args.source_run.resolve(),
        args.dataset.resolve(),
        args.tokenizer_json.resolve(),
    )
    print(json.dumps({
        "run_id": result["run_id"],
        "status": result["status"],
        "decision": result["decision"],
        "provider_requests": result["provider_requests"],
        "summary": result["summary"],
    }, ensure_ascii=False, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
