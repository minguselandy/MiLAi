from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Literal, cast

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from milai.adapters.agent_prefetch import PrefetchContext
from milai.adapters.provider_execution import (
    JsonCompletionTransport,
    ProviderExecutionGateway,
    ProviderRequest,
)

from evals.benchmark import dg11_holdout, dg11_measurement
from evals.benchmark import lme_product_smoke as benchmark
from scripts import dg11_state
from scripts import run_dg10_benchmark_dev_smoke as scorer_v1

INPUTS = ROOT / "var/dg11/holdout/v1/holdout-inputs.json"
OLD_CONTEXTS = ROOT / "var/dg11/runs/dg11-holdout-20260823-001/contexts-dg11-current.json"
OLD_SCORES = ROOT / "var/dg11/runs/dg11-holdout-20260823-001/scored-records.json"
DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
ENV_FILE = ROOT / "runtime/.env"
PYTHON = ROOT / "runtime/.venv/bin/python"
MCP_PYTHON = ROOT / "integrations/mcp/.venv/bin/python"
TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
ENDPOINT = "http://127.0.0.1:7860"
EXPECTED_MULTI = 30
EXPECTED_SINGLE = 31
EXPECTED_CASES = EXPECTED_MULTI + EXPECTED_SINGLE
ANSWER_WORKERS = 2


def _average(records: list[dict[str, Any]], field: str) -> float:
    if not records:
        return 0.0
    return round(mean(float(record[field]) for record in records), 6)


def _context(record: dict[str, Any]) -> PrefetchContext:
    value = record["context"]
    status = cast(
        Literal["NO_MEMORY", "AVAILABLE", "UNCERTAIN", "UNAVAILABLE"],
        value["status"],
    )
    return PrefetchContext(
        status=status,
        rendered=str(value["rendered"]),
        context_sha256=str(value["context_sha256"]),
        trace_id=None,
        request_id=None,
        claim_refs=(),
        evidence_refs=(),
        open_issue_ids=(),
        degraded_components=(),
        abstention_reason=None,
        compiler_version="DG11_R02_PRODUCTION_B3",
    )


def _prepare_contexts(
    run_dir: Path,
    cases: list[dict[str, Any]],
    *,
    contexts_from: Path | None = None,
) -> Path:
    input_path = run_dir / "label-free-inputs.json"
    output_path = run_dir / "production-contexts.json"
    dg11_state.atomic_json(
        input_path,
        {
            "schema": "milai.dg11.holdout-inputs.v1",
            "label_fields_present": False,
            "source_ids": [case["source_id"] for case in cases],
            "cases": cases,
        },
    )
    if contexts_from is not None:
        if not contexts_from.is_file():
            raise RuntimeError(f"R02 reusable contexts do not exist: {contexts_from}")
        shutil.copyfile(contexts_from, output_path)
        return output_path
    if output_path.exists():
        return output_path
    environment = dict(os.environ)
    environment.update(
        {
            "DG10_MCP_HOST_PYTHON": str(MCP_PYTHON),
            "PYTHONPATH": str(ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    command = [
        str(PYTHON),
        "-m",
        "evals.benchmark.dg11_holdout_context_worker",
        "--inputs",
        str(input_path),
        "--output",
        str(output_path),
        "--env-file",
        str(ENV_FILE),
        "--identity",
        "current",
        "--workers",
        "2",
        "--expected-cases",
        str(EXPECTED_CASES),
        "--recall-limit",
        "3",
    ]
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    if completed.returncode != 0:
        raise RuntimeError("R02 production context worker failed")
    return output_path


def _retrieval_measurements(
    cases: dict[str, dict[str, Any]],
    current_records: dict[str, dict[str, Any]],
    old_records: dict[str, dict[str, Any]],
    rows: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    tokenizer = Tokenizer.from_file(str(TOKENIZER))
    records = []
    for source_id, case in cases.items():
        current = current_records[source_id]
        old = old_records[source_id]
        relevant = {str(value) for value in rows[source_id]["answer_session_ids"]}
        answers = benchmark.scoring._answer_values(rows[source_id]["answer"])
        current_ids = [str(value) for value in current["trace"]["retrieved_session_ids"]]
        old_ids = [str(value) for value in old["trace"]["retrieved_session_ids"]]
        current_hits = relevant.intersection(current_ids)
        old_hits = relevant.intersection(old_ids)
        reranker_items = [
            item.get("reranker")
            for item in current["trace"]["retrieved_items"]
            if isinstance(item, dict) and isinstance(item.get("reranker"), dict)
        ]
        records.append(
            {
                "source_id": source_id,
                "category": case["category"],
                "current_retrieved_session_ids": current_ids,
                "old_retrieved_session_ids": old_ids,
                "current_hit": int(bool(current_hits)),
                "old_hit": int(bool(old_hits)),
                "current_coverage": round(len(current_hits) / len(relevant), 6),
                "old_coverage": round(len(old_hits) / len(relevant), 6),
                "current_answer_span": int(
                    dg11_measurement.answer_span_present(
                        current["context"]["rendered"], answers
                    )
                ),
                "old_answer_span": int(
                    dg11_measurement.answer_span_present(old["context"]["rendered"], answers)
                ),
                "memory_tokens": len(
                    tokenizer.encode(str(current["context"]["rendered"])).ids
                ),
                "reranker": reranker_items[0] if reranker_items else None,
                "reranker_expected": bool(current_ids),
                "reranker_result_count": len(reranker_items),
                "recall_status": current["trace"].get("recall_status"),
                "degraded_components": current["trace"].get("degraded_components", []),
            }
        )
    return records


def _retrieval_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    multi = [record for record in records if record["category"] == "multi-session"]
    single = [record for record in records if record["category"] != "multi-session"]
    current_multi_hits = [record for record in multi if record["current_hit"]]
    old_multi_hits = [record for record in multi if record["old_hit"]]
    rerankers = [record["reranker"] for record in records if record["reranker"]]
    expected_rerankers = [record for record in records if record["reranker_expected"]]
    missing_rerankers = [record for record in expected_rerankers if not record["reranker"]]
    unexpected_rerankers = [
        record
        for record in records
        if not record["reranker_expected"] and record["reranker"]
    ]
    frozen_identity = {
        "model_id": "cross-encoder/ms-marco-MiniLM-L6-v2",
        "revision": "233902d25c440f23af6f7d6e94d2946bac0bee0a",
        "model_sha256": "3573b6b9593cb2f75987a31815d409ca3dd8808629118fd20451bb1a5d90cec7",
    }
    identity_mismatches = [
        value
        for value in rerankers
        if any(value.get(field) != expected for field, expected in frozen_identity.items())
    ]
    return {
        "case_count": len(records),
        "multi_session_count": len(multi),
        "single_session_count": len(single),
        "multi_current_hit_at_3": _average(multi, "current_hit"),
        "multi_old_hit_at_3": _average(multi, "old_hit"),
        "multi_current_relevant_coverage_at_3": _average(multi, "current_coverage"),
        "multi_old_relevant_coverage_at_3": _average(multi, "old_coverage"),
        "multi_current_answer_span_survival_on_hit": _average(
            current_multi_hits, "current_answer_span"
        ),
        "multi_old_answer_span_survival_on_hit": _average(
            old_multi_hits, "old_answer_span"
        ),
        "single_current_relevant_coverage_at_3": _average(single, "current_coverage"),
        "single_old_relevant_coverage_at_3": _average(single, "old_coverage"),
        "memory_tokens_mean": round(mean(record["memory_tokens"] for record in records), 3),
        "memory_tokens_max": max(record["memory_tokens"] for record in records),
        "reranker_expected_case_count": len(expected_rerankers),
        "reranker_inference_batches": len(rerankers),
        "reranker_missing_case_count": len(missing_rerankers),
        "reranker_unexpected_case_count": len(unexpected_rerankers),
        "reranker_identity_mismatch_case_count": len(identity_mismatches),
        "reranker_scored_pairs": sum(int(value["pairs"]) for value in rerankers),
        "reranker_latency_ms_mean": round(
            mean(float(value["duration_ms"]) for value in rerankers), 3
        ),
        "reranker_latency_ms_max": round(
            max(float(value["duration_ms"]) for value in rerankers), 3
        ),
        "reranker_model_id": rerankers[0]["model_id"] if rerankers else None,
        "reranker_revision": rerankers[0]["revision"] if rerankers else None,
        "reranker_model_sha256": rerankers[0]["model_sha256"] if rerankers else None,
        "degraded_case_count": sum(bool(record["degraded_components"]) for record in records),
    }


def _answer(
    run_id: str,
    run_dir: Path,
    ordered_cases: list[dict[str, Any]],
    contexts: dict[str, dict[str, Any]],
    rows: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    now = datetime.now(UTC)
    manifest_path = run_dir / "provider-manifest.json"
    ledger_path = run_dir / "provider-ledger.jsonl"
    dg11_state.atomic_json(
        manifest_path,
        {
            "schema": "milai.provider.dev-run.v1",
            "run_id": run_id,
            "phase": "dev",
            "provider": "local_vllm",
            "endpoint_identity": ENDPOINT,
            "model_id": benchmark.MODEL_ID,
            "dataset_manifest_sha256": dg11_state.sha256(run_dir / "label-free-inputs.json"),
            "prompt_template_sha256": benchmark.prompt_contract_sha256(),
            "max_native_requests": EXPECTED_CASES,
            "max_prompt_tokens": EXPECTED_CASES * benchmark.PROMPT_TOKEN_BUDGET,
            "max_completion_tokens": EXPECTED_CASES * benchmark.MAX_OUTPUT_TOKENS,
            "deadline": (now + timedelta(minutes=30)).isoformat(),
            "expires_at": (now + timedelta(minutes=40)).isoformat(),
            "synthetic_or_deidentified_only": True,
            "closed_test_access": False,
        },
    )
    gateway = ProviderExecutionGateway(manifest_path, ledger_path)
    transport = JsonCompletionTransport()
    def answer_one(index: int, raw_case: dict[str, Any]) -> dict[str, Any]:
        source_id = str(raw_case["source_id"])
        case = dg11_holdout.product_case(raw_case)
        context = _context(contexts[source_id])
        messages = benchmark._messages(case.question, case.question_at, context)
        prompt_tokens = benchmark._count_prompt_tokens(ENDPOINT, messages)
        completion = gateway.execute(
            ProviderRequest(
                logical_request_id=f"{run_id}-{index + 1:02d}-b3",
                transport="json",
                payload=benchmark._payload(messages, f"{run_id}-{source_id}"),
                prompt_token_budget=benchmark.PROMPT_TOKEN_BUDGET,
                completion_token_budget=benchmark.MAX_OUTPUT_TOKENS,
                timeout_seconds=180,
            ),
            transport,
            benchmark._parse,
        )
        if completion.prompt_tokens != prompt_tokens:
            raise RuntimeError("R02 target tokenizer recount differs from native usage")
        answer = scorer_v1._parse_answer(completion.value)
        labels = benchmark.scoring._answer_values(rows[source_id]["answer"])
        return {
            "source_id": source_id,
            "category": raw_case["category"],
            "answer": answer,
            "scorer_v1": scorer_v1._score(answer, labels),
            "scorer_v2": dg11_measurement.score_v2(answer, labels),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion.completion_tokens,
            "native_request_id": completion.native_request_id,
            "model_calls": 1,
            "hidden_model_calls": 0,
        }

    answer_records_by_index: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=ANSWER_WORKERS) as executor:
        pending = {
            executor.submit(answer_one, index, raw_case): index
            for index, raw_case in enumerate(ordered_cases)
        }
        for completed_count, future in enumerate(as_completed(pending), start=1):
            answer_records_by_index[pending[future]] = future.result()
            print(
                json.dumps(
                    {
                        "phase": "answer",
                        "completed": completed_count,
                        "total": EXPECTED_CASES,
                        "workers": ANSWER_WORKERS,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    answer_records = [
        answer_records_by_index[index] for index in range(len(ordered_cases))
    ]
    return answer_records, gateway.read_ledger()


def _f1(records: list[dict[str, Any]]) -> float:
    return round(mean(float(record["scorer_v1"]["normalized_f1"]) for record in records), 6)


def run(run_id: str, *, contexts_from: Path | None = None) -> dict[str, Any]:
    run_dir = ROOT / "var/dg11/runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    input_payload = json.loads(INPUTS.read_text(encoding="utf-8"))
    ordered_cases = [
        case
        for case in input_payload["cases"]
        if case["category"] == "multi-session"
        or str(case["category"]).startswith("single-session-")
    ]
    multi_count = sum(case["category"] == "multi-session" for case in ordered_cases)
    if len(ordered_cases) != EXPECTED_CASES or multi_count != EXPECTED_MULTI:
        raise RuntimeError("R02 production gate denominator drifted")
    cases = {str(case["source_id"]): case for case in ordered_cases}
    context_path = _prepare_contexts(
        run_dir,
        ordered_cases,
        contexts_from=contexts_from,
    )
    current_payload = json.loads(context_path.read_text(encoding="utf-8"))
    old_payload = json.loads(OLD_CONTEXTS.read_text(encoding="utf-8"))
    current_records = {
        str(record["source_id"]): record for record in current_payload["records"]
    }
    old_records = {str(record["source_id"]): record for record in old_payload["records"]}
    rows = {
        str(row["question_id"]): row
        for row in json.loads(DATASET.read_text(encoding="utf-8"))
        if row.get("question_id") in cases
    }
    if set(current_records) != set(cases) or set(cases).difference(rows, old_records):
        raise RuntimeError("R02 production gate source identity drifted")
    retrieval_records = _retrieval_measurements(
        cases, current_records, old_records, rows
    )
    retrieval_summary = _retrieval_summary(retrieval_records)
    dg11_state.atomic_json(
        run_dir / "retrieval-result.json",
        {"summary": retrieval_summary, "records": retrieval_records},
    )
    retrieval_gates = {
        "multi_session_relevant_coverage_gt_current_dg11": (
            retrieval_summary["multi_current_relevant_coverage_at_3"]
            > retrieval_summary["multi_old_relevant_coverage_at_3"]
        ),
        "multi_session_answer_span_survival_gt_current_dg11": (
            retrieval_summary["multi_current_answer_span_survival_on_hit"]
            > retrieval_summary["multi_old_answer_span_survival_on_hit"]
        ),
        "single_session_retrieval_coverage_regression_gte_minus_0_01": (
            retrieval_summary["single_current_relevant_coverage_at_3"]
            - retrieval_summary["single_old_relevant_coverage_at_3"]
            >= -0.01
        ),
        "memory_token_ceiling_unchanged": retrieval_summary["memory_tokens_max"] <= 512,
        "reranker_one_batch_per_retrieved_case": (
            retrieval_summary["reranker_inference_batches"]
            == retrieval_summary["reranker_expected_case_count"]
            and retrieval_summary["reranker_missing_case_count"] == 0
            and retrieval_summary["reranker_unexpected_case_count"] == 0
        ),
        "reranker_identity_frozen": (
            retrieval_summary["reranker_model_sha256"]
            == "3573b6b9593cb2f75987a31815d409ca3dd8808629118fd20451bb1a5d90cec7"
            and retrieval_summary["reranker_identity_mismatch_case_count"] == 0
        ),
        "retrieval_degraded_cases_zero": retrieval_summary["degraded_case_count"] == 0,
    }
    if not all(retrieval_gates.values()):
        result = {
            "schema": "milai.dg11.r02-production-gate.v1",
            "run_id": run_id,
            "work_package": "DG11-R02",
            "status": "REVISE",
            "decision": "REVISE_B3_BEFORE_ANSWER",
            "provider_requests": 0,
            "hidden_provider_calls": 0,
            "development_ai_reviews": 0,
            "retrieval": retrieval_summary,
            "gates": retrieval_gates,
            "records": retrieval_records,
        }
        dg11_state.atomic_json(run_dir / "result.json", result)
        return result

    answers, ledger = _answer(run_id, run_dir, ordered_cases, current_records, rows)
    old_scores_payload = json.loads(OLD_SCORES.read_text(encoding="utf-8"))
    old_scores = {
        (str(record["source_id"]), str(record["arm"])): record
        for record in old_scores_payload["records"]
    }
    multi_answers = [record for record in answers if record["category"] == "multi-session"]
    single_answers = [record for record in answers if record["category"] != "multi-session"]
    multi_dg10 = [
        old_scores[(record["source_id"], "MILAI_DG10_FROZEN")]
        for record in multi_answers
    ]
    multi_old_dg11 = [
        old_scores[(record["source_id"], "MILAI_DG11_CURRENT")]
        for record in multi_answers
    ]
    single_dg10 = [
        old_scores[(record["source_id"], "MILAI_DG10_FROZEN")]
        for record in single_answers
    ]
    single_old_dg11 = [
        old_scores[(record["source_id"], "MILAI_DG11_CURRENT")]
        for record in single_answers
    ]
    terminals = [event for event in ledger if event.get("event") == "PROVIDER_TERMINAL"]
    posts = [event for event in ledger if event.get("event") == "POST_PROVIDER_TERMINAL"]
    reservations = [event for event in ledger if event.get("event") == "RESERVED"]
    answer_summary = {
        "multi_current_f1": _f1(multi_answers),
        "multi_dg10_f1": _f1(multi_dg10),
        "multi_old_dg11_f1": _f1(multi_old_dg11),
        "single_current_f1": _f1(single_answers),
        "single_dg10_f1": _f1(single_dg10),
        "single_old_dg11_f1": _f1(single_old_dg11),
    }
    gates = {
        **retrieval_gates,
        "multi_session_f1_gte_dg10": (
            answer_summary["multi_current_f1"] >= answer_summary["multi_dg10_f1"]
        ),
        "single_session_f1_regression_gte_minus_0_01": (
            answer_summary["single_current_f1"]
            - answer_summary["single_old_dg11_f1"]
            >= -0.01
        ),
        "single_session_f1_gte_dg10_minus_0_01": (
            answer_summary["single_current_f1"] - answer_summary["single_dg10_f1"]
            >= -0.01
        ),
        "provider_denominator_exact": (
            len(reservations) == len(terminals) == len(posts) == EXPECTED_CASES
        ),
        "one_answer_call_per_case": len(answers) == EXPECTED_CASES,
        "hidden_answer_calls_zero": True,
    }
    status = "PASS" if all(gates.values()) else "REVISE"
    result = {
        "schema": "milai.dg11.r02-production-gate.v1",
        "run_id": run_id,
        "work_package": "DG11-R02",
        "status": status,
        "decision": "KEEP_B3_PRODUCTION" if status == "PASS" else "REVISE_B3",
        "provider_requests": len(terminals),
        "hidden_provider_calls": 0,
        "development_ai_reviews": 0,
        "retrieval": retrieval_summary,
        "answer": answer_summary,
        "gates": gates,
        "records": {"retrieval": retrieval_records, "answer": answers},
        "finished_at": datetime.now(UTC).isoformat(),
    }
    dg11_state.atomic_json(run_dir / "result.json", result)
    dg11_state.atomic_json(ROOT / "var/dg11/dev/latest-result.json", result)
    dg11_state.append_ledger(
        {
            "run_id": run_id,
            "work_package": "DG11-R02",
            "status": status,
            "decision": result["decision"],
            "provider_requests": len(terminals),
            "development_ai_reviews": 0,
            "metrics": {"retrieval": retrieval_summary, "answer": answer_summary},
        }
    )
    state = json.loads(dg11_state.CURRENT_STATE.read_text(encoding="utf-8"))
    state.setdefault("recovery_work_packages", {})["DG11-R02"] = (
        "PASS" if status == "PASS" else "IN_PROGRESS"
    )
    state["recovery_phase"] = "R02_PASS" if status == "PASS" else "R02_IN_PROGRESS"
    state["latest_result"] = run_id
    state["development_ai_reviews"] = 0
    dg11_state.atomic_json(dg11_state.CURRENT_STATE, state)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--contexts-from", type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    result = run(args.run_id, contexts_from=args.contexts_from)
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "decision": result["decision"],
                "provider_requests": result["provider_requests"],
                "retrieval": result["retrieval"],
                "answer": result.get("answer"),
                "gates": result["gates"],
                "duration_seconds": round(time.monotonic() - started, 3),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
