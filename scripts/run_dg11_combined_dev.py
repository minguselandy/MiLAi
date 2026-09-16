from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from milai.adapters.provider_execution import (
    JsonCompletionTransport,
    ProviderExecutionGateway,
    ProviderRequest,
)

from evals.benchmark import dg11_measurement
from evals.benchmark import lme_product_smoke as benchmark
from scripts import dg11_state
from scripts import run_dg10_benchmark_dev_smoke as scorer_v1
from scripts.run_dg11_temporal_dev import _derived_from_context

DEFAULT_SOURCE_RUN = ROOT / "var/dg10/runs/lme-dev-20260823-004"
DEFAULT_DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
DEFAULT_ENV_FILE = ROOT / "runtime/.env"
DEFAULT_ENDPOINT = "http://127.0.0.1:7860"
RUNS_ROOT = ROOT / "var/dg11/runs"
LATEST_RESULT = ROOT / "var/dg11/dev/combined-latest-result.json"
EFFICIENCY_RESULT = ROOT / "var/dg11/efficiency/latest-result.json"
FUNCTIONAL_RESULT = ROOT / "var/dg11/functional/latest-result.json"
AGENTIC_RESULT = ROOT / "var/dg11/agentic/latest-result.json"
_RUN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{7,95}")
_DEV_GENERATION_SEED_NAMESPACE = "dg11-combined-dev-20260823-002"


class CombinedDevError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CombinedDevError(f"expected JSON object: {path}")
    return value


def _aggregate(records: Sequence[Mapping[str, Any]], scorer: str) -> dict[str, Any]:
    if not records:
        raise CombinedDevError("cannot aggregate an empty record group")
    return {
        "case_count": len(records),
        "exact_match_mean": round(
            mean(float(record[scorer]["exact_match"]) for record in records), 6
        ),
        "normalized_f1_mean": round(
            mean(float(record[scorer]["normalized_f1"]) for record in records), 6
        ),
    }


def _baseline_records(path: Path, selected: set[str]) -> list[dict[str, Any]]:
    payload = _load_object(path)
    expected = {f"longmemeval:{source_id}" for source_id in selected}
    records = [
        dict(record)
        for record in payload.get("records", [])
        if isinstance(record, dict)
        and record.get("arm") == "MILAI_T3A"
        and record.get("case_id") in expected
    ]
    if len(records) != 50 or {str(record["case_id"]) for record in records} != expected:
        raise CombinedDevError("frozen DG10 DEV denominator drifted")
    return records


def _category_metrics(
    records: Sequence[Mapping[str, Any]], scorer: str
) -> dict[str, dict[str, Any]]:
    grouped: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["category"])].append(record)
    return {
        category: _aggregate(group, scorer)
        for category, group in sorted(grouped.items())
    }


def _supporting_gates() -> tuple[bool, bool, dict[str, Any]]:
    efficiency = _load_object(EFFICIENCY_RESULT)
    functional = _load_object(FUNCTIONAL_RESULT)
    agentic = _load_object(AGENTIC_RESULT)
    efficiency_pass = efficiency.get("status") == "PASS" and all(
        value.get("status") == "PASS"
        for value in (efficiency.get("classification") or {}).values()
        if isinstance(value, dict)
    )
    functional_gates = (functional.get("classification") or {}).get("gates") or {}
    agentic_gates = agentic.get("gates") or {}
    safety_pass = (
        functional.get("status") == "PASS"
        and functional_gates.get("canonical_mutation_semantics_unchanged") is True
        and functional_gates.get("secret_private_content_leakage_zero") is True
        and agentic.get("status") == "PASS"
        and agentic_gates.get("wrong_certain_actions_zero") is True
        and agentic_gates.get("stale_revoked_actions_zero") is True
    )
    return (
        efficiency_pass,
        safety_pass,
        {
            "efficiency_run_id": efficiency.get("run_id"),
            "functional_run_id": functional.get("run_id"),
            "agentic_run_id": agentic.get("run_id"),
        },
    )


def _record_state(result: dict[str, Any]) -> None:
    dg11_state.atomic_json(LATEST_RESULT, result)
    current = _load_object(dg11_state.CURRENT_STATE)
    current["phase"] = (
        "DEV_CONVERGED" if result["status"] == "PASS" else "DEV_ITERATION"
    )
    current["work_packages"]["DG11-08"] = (
        "PASS" if result["status"] == "PASS" else "IN_PROGRESS"
    )
    current["latest_result"] = result["run_id"]
    current["development_ai_reviews"] = 0
    dg11_state.atomic_json(dg11_state.CURRENT_STATE, current)
    dg11_state.append_ledger(
        {
            "run_id": result["run_id"],
            "work_package": "DG11-08",
            "status": result["status"],
            "provider_requests": result["provider_requests"],
            "development_ai_reviews": 0,
            "metrics": result["summary"],
        }
    )


def run(
    run_id: str,
    *,
    source_run: Path,
    dataset: Path,
    env_file: Path,
    endpoint: str,
    workers: int = 2,
) -> dict[str, Any]:
    if _RUN_ID.fullmatch(run_id) is None:
        raise CombinedDevError("run_id must be 8-96 lowercase URL-safe characters")
    if not 1 <= workers <= 8:
        raise CombinedDevError("workers must be between 1 and 8")
    source_report_path = source_run / "report.json"
    source_raw_path = source_run / "raw-records.json"
    source_report = _load_object(source_report_path)
    source_ids = tuple(
        str(value) for value in source_report["dataset"]["selected_source_ids"]
    )
    if len(source_ids) != 50 or len(set(source_ids)) != 50:
        raise CombinedDevError("DG10 DEV selected source denominator drifted")
    cases, dataset_meta = benchmark._load_cases(
        dataset,
        source_ids=source_ids,
        phase="SMOKE",
    )
    baseline = _baseline_records(source_raw_path, set(source_ids))
    baseline_enriched = [
        {
            **record,
            "scorer_v1": scorer_v1._score(
                str(record["answer"]), [str(value) for value in record["gold_answers"]]
            ),
            "scorer_v2": dg11_measurement.score_v2(
                str(record["answer"]), [str(value) for value in record["gold_answers"]]
            ),
        }
        for record in baseline
    ]
    run_root = RUNS_ROOT / run_id
    try:
        run_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise CombinedDevError(f"run_id already exists: {run_id}") from exc
    started_at = datetime.now(UTC)
    manifest = {
        "schema": "milai.provider.dev-run.v1",
        "run_id": run_id,
        "phase": "dev",
        "provider": "local_vllm",
        "endpoint_identity": endpoint,
        "model_id": benchmark.MODEL_ID,
        "dataset_manifest_sha256": hashlib.sha256(
            _canonical(
                {
                    "dataset_sha256": dg11_state.sha256(dataset),
                    "source_ids": list(source_ids),
                }
            )
        ).hexdigest(),
        "prompt_template_sha256": benchmark.prompt_contract_sha256(),
        "max_native_requests": 50,
        "max_prompt_tokens": 50 * benchmark.PROMPT_TOKEN_BUDGET,
        "max_completion_tokens": 50 * benchmark.MAX_OUTPUT_TOKENS,
        "deadline": (started_at + timedelta(minutes=45)).isoformat(),
        "expires_at": (started_at + timedelta(minutes=55)).isoformat(),
        "synthetic_or_deidentified_only": True,
        "closed_test_access": False,
    }
    manifest_path = run_root / "provider-manifest.json"
    ledger_path = run_root / "provider-ledger.jsonl"
    dg11_state.atomic_json(manifest_path, manifest)
    gateway = ProviderExecutionGateway(manifest_path, ledger_path)
    transport = JsonCompletionTransport()
    records: list[dict[str, Any]] = []

    # Runtime setup dominates this workload (~40 seconds/case). Each case uses
    # an isolated temporary database, so prepare those contexts concurrently.
    # ``executor.map`` preserves the frozen case order, and provider calls stay
    # on the main thread so ledger order and the one-call denominator remain
    # deterministic.
    def prepare_case(case: benchmark.ProductSmokeCase) -> tuple[Any, dict[str, Any]]:
        return benchmark._runtime_context(case=case, env_file=env_file)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dg11-runtime") as pool:
        futures = {
            pool.submit(prepare_case, case): index for index, case in enumerate(cases)
        }
        prepared_cases: list[tuple[Any, dict[str, Any]] | None] = [None] * len(cases)
        for completed_count, future in enumerate(as_completed(futures), start=1):
            case_index = futures[future]
            prepared_cases[case_index] = future.result()
            print(
                json.dumps(
                    {
                        "phase": "runtime_prepare",
                        "completed": completed_count,
                        "total": len(cases),
                        "workers": workers,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    for case_index, (case, prepared) in enumerate(zip(cases, prepared_cases, strict=True)):
        if prepared is None:
            raise CombinedDevError("parallel runtime preparation lost a case result")
        context, trace = prepared
        messages = benchmark._messages(case.question, case.question_at, context)
        no_memory_messages = benchmark._messages(
            case.question, case.question_at, benchmark.PrefetchContext.no_memory()
        )
        prompt_tokens = benchmark._count_prompt_tokens(endpoint, messages)
        no_memory_tokens = benchmark._count_prompt_tokens(endpoint, no_memory_messages)
        memory_tokens = max(0, prompt_tokens - no_memory_tokens)
        if memory_tokens > benchmark.MEMORY_TOKEN_BUDGET:
            raise CombinedDevError(
                f"{case.case_id} exceeds the 512-token memory budget"
            )
        logical_id = f"{run_id}-{case_index + 1:02d}-dg11-current"
        generation_id = (
            f"{_DEV_GENERATION_SEED_NAMESPACE}-{case_index + 1:02d}-dg11-current"
        )
        call_started = time.perf_counter()
        completion = gateway.execute(
            ProviderRequest(
                logical_request_id=logical_id,
                transport="json",
                payload=benchmark._payload(messages, generation_id),
                prompt_token_budget=benchmark.PROMPT_TOKEN_BUDGET,
                completion_token_budget=benchmark.MAX_OUTPUT_TOKENS,
                timeout_seconds=180,
            ),
            transport,
            benchmark._parse,
        )
        if completion.prompt_tokens != prompt_tokens:
            raise CombinedDevError("target tokenizer recount differs from native usage")
        answer = scorer_v1._parse_answer(completion.value)
        answers = [str(value) for value in case.answers]
        relevant = set(dataset_meta["answer_session_ids"][case.source_case_id])
        retrieved = [str(value) for value in trace["retrieved_session_ids"]]
        hits = relevant.intersection(retrieved)
        records.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "question": case.question,
                "gold_answers": answers,
                "answer": answer,
                "scorer_v1": scorer_v1._score(answer, answers),
                "scorer_v2": dg11_measurement.score_v2(answer, answers),
                "retrieved_session_ids": retrieved,
                "retrieval_hit_at_3": int(bool(hits)),
                "relevant_coverage_at_3": (
                    round(len(hits) / len(relevant), 6) if relevant else 0.0
                ),
                "answer_span_present": dg11_measurement.answer_span_present(
                    context.rendered, answers
                ),
                "derived_query_result": _derived_from_context(context.rendered),
                "memory_status": context.status,
                "memory_tokens": memory_tokens,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion.completion_tokens,
                "answer_latency_ms": round(
                    (time.perf_counter() - call_started) * 1000, 3
                ),
                "runtime_trace": trace,
                "native_request_id": completion.native_request_id,
                "model_calls": 1,
                "hidden_model_calls": 0,
            }
        )
    ledger = gateway.read_ledger()
    terminals = [event for event in ledger if event.get("event") == "PROVIDER_TERMINAL"]
    post = [event for event in ledger if event.get("event") == "POST_PROVIDER_TERMINAL"]
    baseline_v1 = _aggregate(baseline_enriched, "scorer_v1")
    current_v1 = _aggregate(records, "scorer_v1")
    baseline_v2 = _aggregate(baseline_enriched, "scorer_v2")
    current_v2 = _aggregate(records, "scorer_v2")
    baseline_category = _category_metrics(baseline_enriched, "scorer_v1")
    current_category = _category_metrics(records, "scorer_v1")
    category_delta = {
        category: round(
            current_category[category]["normalized_f1_mean"]
            - baseline_category[category]["normalized_f1_mean"],
            6,
        )
        for category in baseline_category
    }
    efficiency_pass, safety_pass, supporting_runs = _supporting_gates()
    gates = {
        "dg11_f1_delta_gte_0_05": (
            current_v1["normalized_f1_mean"] - baseline_v1["normalized_f1_mean"] >= 0.05
        ),
        "dg11_em_delta_gte_zero": (
            current_v1["exact_match_mean"] - baseline_v1["exact_match_mean"] >= 0
        ),
        "assistant_delta_positive": category_delta["single-session-assistant"] > 0,
        "preference_delta_positive": category_delta["single-session-preference"] > 0,
        "knowledge_update_regression_gte_minus_0_02": category_delta["knowledge-update"]
        >= -0.02,
        "multi_session_regression_gte_minus_0_02": category_delta["multi-session"]
        >= -0.02,
        "token_and_serving_gates_pass": efficiency_pass,
        "safety_regressions_zero": safety_pass,
        "provider_denominator_50": (
            len(terminals) == 50
            and len(post) == 50
            and len({event.get("native_request_id") for event in terminals}) == 50
        ),
        "one_answer_call_per_case": len(records) == 50,
        "projection_128d_used": all(
            record["runtime_trace"]["embedding"]["projection_dimensions"] == 128
            for record in records
        ),
    }
    passed = all(gates.values())
    result = {
        "schema": "milai.dg11.combined-dev-result.v1",
        "run_id": run_id,
        "work_package": "DG11-08",
        "status": "PASS" if passed else "BELOW_TARGET",
        "decision": "KEEP" if passed else "ITERATE",
        "case_denominator": 50,
        "provider_requests": len(terminals),
        "hidden_provider_calls": 0 if len(terminals) == len(records) else None,
        "development_ai_reviews": 0,
        "runtime_workers": workers,
        "source_run_id": source_run.name,
        "source_raw_sha256": dg11_state.sha256(source_raw_path),
        "dataset_sha256": dg11_state.sha256(dataset),
        "supporting_runs": supporting_runs,
        "baseline": {
            "scorer_v1": baseline_v1,
            "scorer_v2": baseline_v2,
            "category": baseline_category,
        },
        "current": {
            "scorer_v1": current_v1,
            "scorer_v2": current_v2,
            "category": current_category,
        },
        "category_f1_delta": category_delta,
        "summary": {
            "dg10_v1_f1": baseline_v1["normalized_f1_mean"],
            "dg11_v1_f1": current_v1["normalized_f1_mean"],
            "v1_f1_delta": round(
                current_v1["normalized_f1_mean"] - baseline_v1["normalized_f1_mean"],
                6,
            ),
            "dg10_v1_em": baseline_v1["exact_match_mean"],
            "dg11_v1_em": current_v1["exact_match_mean"],
            "v1_em_delta": round(
                current_v1["exact_match_mean"] - baseline_v1["exact_match_mean"], 6
            ),
            "dg10_v2_f1": baseline_v2["normalized_f1_mean"],
            "dg11_v2_f1": current_v2["normalized_f1_mean"],
            "memory_tokens_mean": round(
                mean(record["memory_tokens"] for record in records), 3
            ),
            "memory_tokens_max": max(record["memory_tokens"] for record in records),
            "retrieval_hit_at_3": round(
                mean(record["retrieval_hit_at_3"] for record in records), 6
            ),
            "relevant_coverage_at_3": round(
                mean(record["relevant_coverage_at_3"] for record in records), 6
            ),
            "answer_span_survival_on_hit": round(
                mean(
                    bool(record["answer_span_present"])
                    for record in records
                    if record["retrieval_hit_at_3"] == 1
                ),
                6,
            ),
        },
        "gates": gates,
        "records": records,
        "provider_ledger_summary": {
            "reservations": sum(event.get("event") == "RESERVED" for event in ledger),
            "provider_terminals": len(terminals),
            "post_provider_terminals": len(post),
            "unique_native_request_ids": len(
                {event.get("native_request_id") for event in terminals}
            ),
        },
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
    }
    dg11_state.atomic_json(run_root / "result.json", result)
    _record_state(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the 50-case DG11 combined DEV arm"
    )
    parser.add_argument(
        "--run-id",
        default=(
            "dg11-combined-dev-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        ),
    )
    parser.add_argument("--source-run", type=Path, default=DEFAULT_SOURCE_RUN)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    result = run(
        args.run_id,
        source_run=args.source_run.resolve(),
        dataset=args.dataset.resolve(),
        env_file=args.env_file.resolve(),
        endpoint=args.endpoint,
        workers=args.workers,
    )
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "decision": result["decision"],
                "summary": result["summary"],
                "category_f1_delta": result["category_f1_delta"],
                "gates": result["gates"],
                "provider_requests": result["provider_requests"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
