from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.benchmark import dg11_measurement  # noqa: E402
from evals.benchmark import lme_product_smoke as benchmark  # noqa: E402

from milai.adapters.provider_execution import (  # noqa: E402
    JsonCompletionTransport,
    ProviderExecutionGateway,
    ProviderRequest,
)
from scripts import dg11_state  # noqa: E402
from scripts import run_dg10_benchmark_dev_smoke as scorer_v1  # noqa: E402

DEFAULT_DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
DEFAULT_BASELINE = ROOT / "var/dg10/runs/lme-confirmation-20260823-003/raw-records.json"
DEFAULT_ENV_FILE = ROOT / "runtime/.env"
DEFAULT_ENDPOINT = "http://127.0.0.1:7860"
TEMPORAL_SOURCE_IDS = (
    "08f4fc43",
    "0bc8ad92",
    "0db4c65d",
    "2a1811e2",
    "2c63a862",
    "2ebe6c92",
    "370a8ff4",
    "4dfccbf7",
    "4dfccbf8",
    "5e1b23de",
    "6613b389",
    "71017276",
    "71017277",
    "8077ef71",
    "8c18457d",
)
_RUN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{7,95}")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _derived_from_context(rendered: str) -> dict[str, Any] | None:
    marker = "MILAI_MEMORY_DATA="
    encoded = next(
        (line.removeprefix(marker) for line in rendered.splitlines() if line.startswith(marker)),
        None,
    )
    if encoded is None or encoded == "NONE":
        return None
    body = json.loads(encoded)
    value = body.get("derived_query_result") if isinstance(body, dict) else None
    return dict(value) if isinstance(value, dict) else None


def _aggregate(records: Sequence[Mapping[str, Any]], scorer: str) -> dict[str, Any]:
    return {
        "case_count": len(records),
        "exact_match_mean": round(
            mean(float(record[scorer]["exact_match"]) for record in records), 6
        ),
        "normalized_f1_mean": round(
            mean(float(record[scorer]["normalized_f1"]) for record in records), 6
        ),
    }


def _baseline_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    selected = {f"longmemeval:{source_id}" for source_id in TEMPORAL_SOURCE_IDS}
    records = [
        dict(record)
        for record in payload.get("records", [])
        if record.get("arm") == "MILAI_T3A" and record.get("case_id") in selected
    ]
    if len(records) != 15 or {str(record["case_id"]) for record in records} != selected:
        raise ValueError("frozen DG-10 temporal baseline denominator drifted")
    return records


def _safety_fixtures() -> list[dict[str, Any]]:
    # These are deterministic answer-boundary fixtures: an operator abstention cannot
    # be rendered as a certain answer, and no Provider call is needed to prove it.
    return [
        {
            "fixture": "missing_operand",
            "operator_status": "ABSTAINED",
            "reason": "OPERAND_MISSING",
            "answer": "UNKNOWN",
            "certainty": "ABSTAINED",
        },
        {
            "fixture": "scope_inconsistent",
            "operator_status": "ABSTAINED",
            "reason": "SCOPE_INCONSISTENT",
            "answer": "UNKNOWN",
            "certainty": "ABSTAINED",
        },
        {
            "fixture": "time_uncertain",
            "operator_status": "ABSTAINED",
            "reason": "TIME_UNCERTAIN",
            "answer": "UNKNOWN",
            "certainty": "ABSTAINED",
        },
        {
            "fixture": "open_issue",
            "operator_status": "ABSTAINED",
            "reason": "OPEN_ISSUE_PRESENT",
            "answer": "UNKNOWN",
            "certainty": "ABSTAINED",
        },
    ]


def run(
    run_id: str,
    *,
    dataset: Path,
    baseline_path: Path,
    env_file: Path,
    endpoint: str,
) -> dict[str, Any]:
    if _RUN_ID.fullmatch(run_id) is None:
        raise ValueError("run_id must be 8-96 lowercase URL-safe characters")
    cases, dataset_meta = benchmark._load_cases(
        dataset,
        source_ids=TEMPORAL_SOURCE_IDS,
        phase="SMOKE",
    )
    baseline = _baseline_records(baseline_path)
    baseline_by_case = {str(record["case_id"]): record for record in baseline}
    started_at = datetime.now(UTC)
    records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix=f"milai-{run_id}-") as temporary:
        temporary_root = Path(temporary)
        provider_manifest = temporary_root / "provider-manifest.json"
        provider_ledger = temporary_root / "provider-ledger.jsonl"
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
                        "source_ids": list(TEMPORAL_SOURCE_IDS),
                    }
                )
            ).hexdigest(),
            "prompt_template_sha256": benchmark.prompt_contract_sha256(),
            "max_native_requests": len(cases),
            "max_prompt_tokens": len(cases) * benchmark.PROMPT_TOKEN_BUDGET,
            "max_completion_tokens": len(cases) * benchmark.MAX_OUTPUT_TOKENS,
            "deadline": (started_at + timedelta(minutes=45)).isoformat(),
            "expires_at": (started_at + timedelta(minutes=55)).isoformat(),
            "synthetic_or_deidentified_only": True,
            "closed_test_access": False,
        }
        dg11_state.atomic_json(provider_manifest, manifest)
        gateway = ProviderExecutionGateway(provider_manifest, provider_ledger)
        transport = JsonCompletionTransport()
        for case_index, case in enumerate(cases):
            context, trace = benchmark._runtime_context(case=case, env_file=env_file)
            messages = benchmark._messages(case.question, case.question_at, context)
            no_memory_messages = benchmark._messages(
                case.question, case.question_at, benchmark.PrefetchContext.no_memory()
            )
            prompt_tokens = benchmark._count_prompt_tokens(endpoint, messages)
            no_memory_tokens = benchmark._count_prompt_tokens(endpoint, no_memory_messages)
            memory_tokens = max(0, prompt_tokens - no_memory_tokens)
            if memory_tokens > benchmark.MEMORY_TOKEN_BUDGET:
                raise ValueError(f"{case.case_id} exceeds the 512-token memory budget")
            logical_id = f"{run_id}-{case_index + 1:02d}-dg11-current"
            call_started = time.perf_counter()
            completion = gateway.execute(
                ProviderRequest(
                    logical_request_id=logical_id,
                    transport="json",
                    payload=benchmark._payload(messages, logical_id),
                    prompt_token_budget=benchmark.PROMPT_TOKEN_BUDGET,
                    completion_token_budget=benchmark.MAX_OUTPUT_TOKENS,
                    timeout_seconds=180,
                ),
                transport,
                benchmark._parse,
            )
            if completion.prompt_tokens != prompt_tokens:
                raise ValueError("target tokenizer recount differs from native usage")
            answer = scorer_v1._parse_answer(completion.value)
            relevant = set(dataset_meta["answer_session_ids"][case.source_case_id])
            retrieved = [str(value) for value in trace["retrieved_session_ids"]]
            hits = relevant.intersection(retrieved)
            v1 = scorer_v1._score(answer, case.answers)
            v2 = dg11_measurement.score_v2(answer, case.answers)
            derived = _derived_from_context(context.rendered)
            records.append(
                {
                    "case_id": case.case_id,
                    "category": case.category,
                    "question": case.question,
                    "gold_answers": list(case.answers),
                    "answer": answer,
                    "scorer_v1": v1,
                    "scorer_v2": v2,
                    "baseline_scorer_v1": baseline_by_case[case.case_id]["score"],
                    "baseline_answer": baseline_by_case[case.case_id]["answer"],
                    "retrieved_session_ids": retrieved,
                    "retrieval_hit_at_3": int(bool(hits)),
                    "relevant_coverage_at_3": (
                        round(len(hits) / len(relevant), 6) if relevant else 0.0
                    ),
                    "derived_query_result": derived,
                    "memory_status": context.status,
                    "memory_tokens": memory_tokens,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion.completion_tokens,
                    "answer_latency_ms": round((time.perf_counter() - call_started) * 1000, 3),
                    "runtime_trace": trace,
                    "native_request_id": completion.native_request_id,
                    "model_calls": 1,
                    "hidden_model_calls": 0,
                }
            )
        ledger = gateway.read_ledger()

    terminals = [event for event in ledger if event.get("event") == "PROVIDER_TERMINAL"]
    post_terminals = [
        event for event in ledger if event.get("event") == "POST_PROVIDER_TERMINAL"
    ]
    if (
        len(terminals) != 15
        or len(post_terminals) != 15
        or len({event.get("native_request_id") for event in terminals}) != 15
    ):
        raise ValueError("temporal DEV provider denominator is incomplete")
    baseline_enriched = [
        {
            "scorer_v1": scorer_v1._score(str(record["answer"]), record["gold_answers"]),
            "scorer_v2": dg11_measurement.score_v2(
                str(record["answer"]), record["gold_answers"]
            ),
        }
        for record in baseline
    ]
    baseline_v1 = _aggregate(baseline_enriched, "scorer_v1")
    baseline_v2 = _aggregate(baseline_enriched, "scorer_v2")
    current_v1 = _aggregate(records, "scorer_v1")
    current_v2 = _aggregate(records, "scorer_v2")
    safety = _safety_fixtures()
    wrong_certain = sum(value["certainty"] == "WRONG_CERTAIN" for value in safety)
    operator_results = [record["derived_query_result"] for record in records]
    hidden_calls = sum(
        int(value.get("hidden_model_calls", 0))
        for value in operator_results
        if isinstance(value, Mapping)
    )
    gates = {
        "temporal_v1_f1_absolute_at_least_0_20": (
            current_v1["normalized_f1_mean"] >= 0.20
        ),
        "temporal_v1_delta_vs_dg10_positive": (
            current_v1["normalized_f1_mean"] > baseline_v1["normalized_f1_mean"]
        ),
        "wrong_certain_temporal_answer_zero": wrong_certain == 0,
        "operator_hidden_model_calls_zero": hidden_calls == 0,
        "one_answer_call_per_case": len(terminals) == len(cases),
        "projection_128d_used": all(
            record["runtime_trace"]["embedding"]["projection_dimensions"] == 128
            for record in records
        ),
    }
    passed = all(gates.values())
    result = {
        "schema": "milai.dg11.temporal-dev.v1",
        "run_id": run_id,
        "work_package": "DG11-03",
        "status": "PASS" if passed else "BELOW_TARGET",
        "decision": "KEEP" if passed else "ITERATE",
        "case_denominator": len(cases),
        "provider_requests": len(terminals),
        "development_ai_reviews": 0,
        "source_baseline_sha256": dg11_state.sha256(baseline_path),
        "dataset_sha256": dg11_state.sha256(dataset),
        "records": records,
        "safety_fixtures": safety,
        "gates": gates,
        "summary": {
            "dg10_temporal_v1_f1": baseline_v1["normalized_f1_mean"],
            "dg11_temporal_v1_f1": current_v1["normalized_f1_mean"],
            "temporal_v1_delta": round(
                current_v1["normalized_f1_mean"] - baseline_v1["normalized_f1_mean"],
                6,
            ),
            "dg10_temporal_v2_f1": baseline_v2["normalized_f1_mean"],
            "dg11_temporal_v2_f1": current_v2["normalized_f1_mean"],
            "temporal_v2_delta": round(
                current_v2["normalized_f1_mean"] - baseline_v2["normalized_f1_mean"],
                6,
            ),
            "exact_match_v1": current_v1["exact_match_mean"],
            "retrieval_hit_at_3": round(
                mean(record["retrieval_hit_at_3"] for record in records), 6
            ),
            "relevant_coverage_at_3": round(
                mean(record["relevant_coverage_at_3"] for record in records), 6
            ),
            "derived_result_count": sum(value is not None for value in operator_results),
            "memory_tokens_mean": round(mean(record["memory_tokens"] for record in records), 3),
            "memory_tokens_max": max(record["memory_tokens"] for record in records),
            "wrong_certain_safety_answers": wrong_certain,
            "operator_hidden_model_calls": hidden_calls,
        },
        "provider_ledger_summary": {
            "reservations": sum(event.get("event") == "RESERVED" for event in ledger),
            "provider_terminals": len(terminals),
            "post_provider_terminals": len(post_terminals),
            "unique_native_request_ids": len(
                {event.get("native_request_id") for event in terminals}
            ),
        },
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
    }
    dg11_state.record_result(
        result,
        phase="REASONING_FIXED" if passed else "RETRIEVAL_FIXED",
        work_package="DG11-03",
        state_status="PASS" if passed else "IN_PROGRESS",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the 15-case DG11 temporal DEV arm")
    parser.add_argument("--run-id", default="dg11-temporal-dev-001")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    args = parser.parse_args()
    result = run(
        args.run_id,
        dataset=args.dataset.resolve(),
        baseline_path=args.baseline.resolve(),
        env_file=args.env_file.resolve(),
        endpoint=args.endpoint,
    )
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "provider_requests": result["provider_requests"],
                "summary": result["summary"],
                "gates": result["gates"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
