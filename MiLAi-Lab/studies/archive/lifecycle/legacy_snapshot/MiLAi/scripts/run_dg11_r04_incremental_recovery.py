from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, cast

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
from scripts.run_dg11_r04_combined_dev2 import (
    BASELINES,
    DATASET,
    ENDPOINT,
    EXPECTED_CASES,
    INPUTS,
    WORKERS,
    _aggregate,
    _arm_records,
    _context,
    _evaluate_quality_gates,
    _load_object,
    _mapping,
    _safety_evidence,
    _source_identity,
    _stratified,
)

PRIOR_RUN = ROOT / "var/dg11/runs/dg11-r04-combined-dev2-20260823-001"
NEW_CONTEXTS = (
    ROOT / "var/dg11/runs/dg11-r04-recovery-contexts-20260824-009/contexts.json"
)
TARGETED_RUN = ROOT / "var/dg11/runs/dg11-r04-targeted-recheck-20260823-001"
MAX_INCREMENTAL_CALLS = 60
GENERATION_NAMESPACE = "dg11-r04-incremental-recovery-v1"


class IncrementalRecoveryError(RuntimeError):
    pass


def _sha(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _records_by_source(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise IncrementalRecoveryError("record collection is absent")
    result = {
        str(record["source_id"]): dict(record)
        for record in records
        if isinstance(record, Mapping) and isinstance(record.get("source_id"), str)
    }
    if len(result) != len(records):
        raise IncrementalRecoveryError("record collection has duplicate or invalid source IDs")
    return result


def run(run_id: str) -> dict[str, Any]:
    run_dir = ROOT / "var/dg11/runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    source_identity = _source_identity()
    input_payload = _load_object(INPUTS)
    raw_cases = {
        str(case["source_id"]): dict(case)
        for case in input_payload.get("cases", [])
        if isinstance(case, Mapping) and isinstance(case.get("source_id"), str)
    }
    source_ids = set(raw_cases)
    if len(raw_cases) != EXPECTED_CASES:
        raise IncrementalRecoveryError("R04 input denominator drifted")

    old_context_payload = _load_object(PRIOR_RUN / "contexts.json")
    new_context_payload = _load_object(NEW_CONTEXTS)
    old_contexts = _records_by_source(old_context_payload)
    new_contexts = _records_by_source(new_context_payload)
    if set(old_contexts) != source_ids or set(new_contexts) != source_ids:
        raise IncrementalRecoveryError("old/new context denominator drifted")

    prior_result = _load_object(PRIOR_RUN / "result.json")
    prior_records = _records_by_source(prior_result)
    targeted_result = _load_object(TARGETED_RUN / "result.json")
    targeted_records = _records_by_source(targeted_result)
    if not set(targeted_records).issubset(source_ids):
        raise IncrementalRecoveryError("targeted result source IDs drifted")

    current_prompt_sha = benchmark.prompt_contract_sha256()
    prior_manifest = _load_object(PRIOR_RUN / "provider-manifest.json")
    targeted_manifest = _load_object(TARGETED_RUN / "provider-manifest.json")
    prompt_identity_exact = (
        prior_manifest.get("prompt_template_sha256")
        == targeted_manifest.get("prompt_template_sha256")
        == current_prompt_sha
    )
    if not prompt_identity_exact:
        raise IncrementalRecoveryError("answer prompt identity drifted")

    prepared: dict[str, dict[str, Any]] = {}
    changed_source_ids: list[str] = []
    unchanged_source_ids: list[str] = []
    targeted_reuse_source_ids: list[str] = []
    fresh_source_ids: list[str] = []
    for source_id in input_payload["source_ids"]:
        source_id = str(source_id)
        case = dg11_holdout.product_case(raw_cases[source_id])
        old_raw = old_contexts[source_id].get("context")
        new_raw = new_contexts[source_id].get("context")
        if not isinstance(old_raw, Mapping) or not isinstance(new_raw, Mapping):
            raise IncrementalRecoveryError(f"invalid context record: {source_id}")
        old_context = _context(old_raw)
        new_context = _context(new_raw)
        old_messages = benchmark._messages(case.question, case.question_at, old_context)
        new_messages = benchmark._messages(case.question, case.question_at, new_context)
        old_prompt_sha = _sha(old_messages)
        new_prompt_sha = _sha(new_messages)
        changed = old_prompt_sha != new_prompt_sha
        if changed:
            changed_source_ids.append(source_id)
        else:
            unchanged_source_ids.append(source_id)

        prompt_tokens = benchmark._count_prompt_tokens(ENDPOINT, new_messages)
        no_memory_tokens = benchmark._count_prompt_tokens(
            ENDPOINT,
            benchmark._messages(case.question, case.question_at, PrefetchContext.no_memory()),
        )
        memory_tokens = max(0, prompt_tokens - no_memory_tokens)
        if memory_tokens > benchmark.MEMORY_TOKEN_BUDGET:
            raise IncrementalRecoveryError(f"memory token ceiling exceeded: {source_id}")

        answer_source = "PRIOR_COMBINED_EXACT_PROMPT"
        source_record = prior_records[source_id]
        if changed:
            targeted = targeted_records.get(source_id)
            if (
                targeted is not None
                and targeted.get("context_sha256") == new_context.context_sha256
                and int(targeted.get("prompt_tokens", -1)) == prompt_tokens
            ):
                answer_source = "TARGETED_RECOVERY_EXACT_PROMPT"
                source_record = targeted
                targeted_reuse_source_ids.append(source_id)
            else:
                answer_source = "FRESH_INCREMENTAL"
                fresh_source_ids.append(source_id)
        prepared[source_id] = {
            "source_id": source_id,
            "raw_case": raw_cases[source_id],
            "case": case,
            "context": new_context,
            "messages": new_messages,
            "prompt_sha256": new_prompt_sha,
            "prompt_tokens": prompt_tokens,
            "memory_tokens": memory_tokens,
            "trace": new_contexts[source_id].get("trace"),
            "answer_source": answer_source,
            "source_record": source_record,
        }

    if len(changed_source_ids) > MAX_INCREMENTAL_CALLS:
        raise IncrementalRecoveryError(
            f"changed prompt count exceeds targeted budget: {len(changed_source_ids)}"
        )
    if len(fresh_source_ids) > MAX_INCREMENTAL_CALLS:
        raise IncrementalRecoveryError(
            f"fresh answer count exceeds targeted budget: {len(fresh_source_ids)}"
        )

    dataset_rows = json.loads(DATASET.read_text(encoding="utf-8"))
    rows = {
        str(row["question_id"]): row
        for row in dataset_rows
        if isinstance(row, dict) and str(row.get("question_id")) in source_ids
    }
    if set(rows) != source_ids:
        raise IncrementalRecoveryError("scorer rows drifted")

    def record_from_answer(
        item: Mapping[str, Any],
        *,
        answer: str,
        native_request_id: object,
        completion_tokens: int,
        answer_latency_ms: float,
    ) -> dict[str, Any]:
        source_id = str(item["source_id"])
        labels = benchmark.scoring._answer_values(rows[source_id]["answer"])
        answer_sessions = {
            str(value) for value in rows[source_id].get("answer_session_ids", [])
        }
        trace = _mapping(item.get("trace"))
        retrieved = [str(value) for value in trace.get("retrieved_session_ids", [])]
        hits = answer_sessions.intersection(retrieved)
        context = cast(PrefetchContext, item["context"])
        return {
            "source_id": source_id,
            "case_id": f"longmemeval:{source_id}",
            "category": str(item["raw_case"]["category"]),
            "answer": answer,
            "scorer_v1": scorer_v1._score(answer, labels),
            "scorer_v2": dg11_measurement.score_v2(answer, labels),
            "memory_status": context.status,
            "compiler_version": context.compiler_version,
            "context_sha256": context.context_sha256,
            "prompt_sha256": item["prompt_sha256"],
            "context_chars": len(context.rendered),
            "memory_tokens": item["memory_tokens"],
            "prompt_tokens": item["prompt_tokens"],
            "completion_tokens": completion_tokens,
            "retrieved_session_ids": retrieved,
            "retrieval_hit_at_3": int(bool(hits)),
            "relevant_coverage_at_3": (
                round(len(hits) / len(answer_sessions), 6) if answer_sessions else 0.0
            ),
            "answer_span_present": dg11_measurement.answer_span_present(
                context.rendered, labels
            ),
            "runtime_trace": trace,
            "answer_latency_ms": answer_latency_ms,
            "native_request_id": native_request_id,
            "model_calls": 1,
            "hidden_model_calls": 0,
            "answer_source": item["answer_source"],
        }

    records_by_source: dict[str, dict[str, Any]] = {}
    for source_id in unchanged_source_ids + targeted_reuse_source_ids:
        item = prepared[source_id]
        reused_source_record = cast(Mapping[str, Any], item["source_record"])
        records_by_source[source_id] = record_from_answer(
            item,
            answer=str(reused_source_record["answer"]),
            native_request_id=reused_source_record.get("native_request_id"),
            completion_tokens=int(reused_source_record.get("completion_tokens", 0)),
            answer_latency_ms=float(
                reused_source_record.get("answer_latency_ms", 0.0)
            ),
        )

    manifest_path = run_dir / "provider-manifest.json"
    ledger_path = run_dir / "provider-ledger.jsonl"
    gateway: ProviderExecutionGateway | None = None
    transport: JsonCompletionTransport | None = None
    if fresh_source_ids:
        now = datetime.now(UTC)
        dg11_state.atomic_json(
            manifest_path,
            {
                "schema": "milai.provider.dev-run.v1",
                "run_id": run_id,
                "phase": "dev",
                "provider": "local_vllm",
                "endpoint_identity": ENDPOINT,
                "model_id": benchmark.MODEL_ID,
                "dataset_manifest_sha256": dg11_state.sha256(INPUTS),
                "prompt_template_sha256": current_prompt_sha,
                "max_native_requests": len(fresh_source_ids),
                "max_prompt_tokens": len(fresh_source_ids)
                * benchmark.PROMPT_TOKEN_BUDGET,
                "max_completion_tokens": len(fresh_source_ids)
                * benchmark.MAX_OUTPUT_TOKENS,
                "deadline": (now + timedelta(minutes=20)).isoformat(),
                "expires_at": (now + timedelta(minutes=25)).isoformat(),
                "synthetic_or_deidentified_only": True,
                "closed_test_access": False,
            },
        )
        gateway = ProviderExecutionGateway(manifest_path, ledger_path)
        transport = JsonCompletionTransport()

        def answer_one(index: int, source_id: str) -> tuple[str, dict[str, Any]]:
            item = prepared[source_id]
            assert gateway is not None and transport is not None
            started = time.perf_counter()
            completion = gateway.execute(
                ProviderRequest(
                    logical_request_id=f"{run_id}-{index + 1:03d}-incremental",
                    transport="json",
                    payload=benchmark._payload(
                        cast(list[dict[str, str]], item["messages"]),
                        f"{GENERATION_NAMESPACE}-{source_id}",
                    ),
                    prompt_token_budget=benchmark.PROMPT_TOKEN_BUDGET,
                    completion_token_budget=benchmark.MAX_OUTPUT_TOKENS,
                    timeout_seconds=180,
                ),
                transport,
                benchmark._parse,
            )
            if completion.prompt_tokens != item["prompt_tokens"]:
                raise IncrementalRecoveryError("native tokenizer recount drifted")
            record = record_from_answer(
                item,
                answer=scorer_v1._parse_answer(completion.value),
                native_request_id=completion.native_request_id,
                completion_tokens=completion.completion_tokens,
                answer_latency_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            return source_id, record

        with ThreadPoolExecutor(
            max_workers=WORKERS, thread_name_prefix="r04-incremental"
        ) as pool:
            pending = {
                pool.submit(answer_one, index, source_id): source_id
                for index, source_id in enumerate(fresh_source_ids)
            }
            for completed, future in enumerate(as_completed(pending), start=1):
                source_id, record = future.result()
                records_by_source[source_id] = record
                print(
                    json.dumps(
                        {
                            "phase": "answer",
                            "completed": completed,
                            "total": len(fresh_source_ids),
                            "workers": WORKERS,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )

    if set(records_by_source) != source_ids:
        raise IncrementalRecoveryError("effective answer matrix is incomplete")
    records = [records_by_source[str(value)] for value in input_payload["source_ids"]]

    ledger = gateway.read_ledger() if gateway is not None else []
    event_counts = Counter(str(event.get("event")) for event in ledger)
    terminals = [event for event in ledger if event.get("event") == "PROVIDER_TERMINAL"]
    ledger_exact = (
        event_counts["RESERVED"]
        == event_counts["PROVIDER_TERMINAL"]
        == event_counts["POST_PROVIDER_TERMINAL"]
        == len(fresh_source_ids)
        and all(event.get("status") == "SUCCEEDED" for event in terminals)
        and len({event.get("logical_request_id") for event in terminals})
        == len(fresh_source_ids)
        and len({event.get("native_request_id") for event in terminals})
        == len(fresh_source_ids)
    )

    baseline_payload = _load_object(BASELINES)
    dg10 = _arm_records(baseline_payload, "MILAI_DG10_FROZEN", source_ids)
    lexical = _arm_records(baseline_payload, "NAIVE_RAG", source_ids)
    dg10_v1 = _aggregate(dg10, "scorer_v1")
    dg10_v2 = _aggregate(dg10, "scorer_v2")
    lexical_v1 = _aggregate(lexical, "scorer_v1")
    lexical_v2 = _aggregate(lexical, "scorer_v2")
    current_v1 = _aggregate(records, "scorer_v1")
    current_v2 = _aggregate(records, "scorer_v2")
    dg10_category_v1 = _stratified(dg10, "scorer_v1")
    dg10_category_v2 = _stratified(dg10, "scorer_v2")
    lexical_category_v1 = _stratified(lexical, "scorer_v1")
    lexical_category_v2 = _stratified(lexical, "scorer_v2")
    current_category_v1 = _stratified(records, "scorer_v1")
    current_category_v2 = _stratified(records, "scorer_v2")
    memory_tokens_mean = round(mean(int(record["memory_tokens"]) for record in records), 3)
    safety_pass, safety_evidence = _safety_evidence()
    quality_gates = _evaluate_quality_gates(
        current_v1=current_v1,
        dg10_v1=dg10_v1,
        current_categories=current_category_v1,
        dg10_categories=dg10_category_v1,
        lexical_categories=lexical_category_v1,
        mean_memory_tokens=memory_tokens_mean,
        safety_pass=safety_pass,
    )
    execution_gates = {
        "context_denominator_exact": len(new_contexts) == EXPECTED_CASES,
        "changed_prompts_lte_60": len(changed_source_ids) <= MAX_INCREMENTAL_CALLS,
        "fresh_answer_calls_lte_60": len(fresh_source_ids) <= MAX_INCREMENTAL_CALLS,
        "changed_prompts_fully_covered": set(changed_source_ids)
        == set(fresh_source_ids).union(targeted_reuse_source_ids),
        "unchanged_prompt_reuse_exact": len(unchanged_source_ids)
        + len(changed_source_ids)
        == EXPECTED_CASES,
        "provider_denominator_exact": ledger_exact,
        "one_effective_answer_per_case": len(records) == EXPECTED_CASES,
        "hidden_answer_calls_zero": all(
            int(record["hidden_model_calls"]) == 0 for record in records
        ),
        "memory_token_ceiling_512": max(
            int(record["memory_tokens"]) for record in records
        )
        <= benchmark.MEMORY_TOKEN_BUDGET,
        "prompt_identity_exact": prompt_identity_exact,
        "source_identity_stable": _source_identity() == source_identity,
    }
    gates = {**quality_gates, **execution_gates}
    status = "PASS" if all(gates.values()) else "REVISE"
    summary = {
        "f1_delta_vs_dg10": round(
            current_v1["normalized_f1_mean"] - dg10_v1["normalized_f1_mean"], 6
        ),
        "em_delta_vs_dg10": round(
            current_v1["exact_match_mean"] - dg10_v1["exact_match_mean"], 6
        ),
        "multi_session_f1_delta_vs_dg10": round(
            current_category_v1["multi-session"]["normalized_f1_mean"]
            - dg10_category_v1["multi-session"]["normalized_f1_mean"],
            6,
        ),
        "single_assistant_f1_delta_vs_custom_lexical": round(
            current_category_v1["single-session-assistant"]["normalized_f1_mean"]
            - lexical_category_v1["single-session-assistant"]["normalized_f1_mean"],
            6,
        ),
        "knowledge_update_f1_delta_vs_dg10": round(
            current_category_v1["knowledge-update"]["normalized_f1_mean"]
            - dg10_category_v1["knowledge-update"]["normalized_f1_mean"],
            6,
        ),
        "memory_tokens_mean": memory_tokens_mean,
        "memory_tokens_max": max(int(record["memory_tokens"]) for record in records),
        "retrieval_hit_at_3": round(
            mean(int(record["retrieval_hit_at_3"]) for record in records), 6
        ),
        "relevant_coverage_at_3": round(
            mean(float(record["relevant_coverage_at_3"]) for record in records), 6
        ),
        "answer_span_survival": round(
            mean(bool(record["answer_span_present"]) for record in records), 6
        ),
    }
    result = {
        "schema": "milai.dg11.r04-incremental-recovery.v1",
        "run_id": run_id,
        "work_package": "DG11-R04",
        "status": status,
        "decision": "KEEP_INCREMENTAL_RECOVERY" if status == "PASS" else "REVISE",
        "protocol": {
            "combined_dev2_runs": 1,
            "prior_combined_run": PRIOR_RUN.name,
            "unchanged_answers_reused_only_for_exact_prompt": True,
            "targeted_answer_budget": MAX_INCREMENTAL_CALLS,
            "changed_prompt_count": len(changed_source_ids),
            "fresh_answer_count": len(fresh_source_ids),
            "targeted_reuse_count": len(targeted_reuse_source_ids),
            "prior_combined_reuse_count": len(unchanged_source_ids),
        },
        "changed_source_ids": changed_source_ids,
        "fresh_source_ids": fresh_source_ids,
        "targeted_reuse_source_ids": targeted_reuse_source_ids,
        "provider_requests": len(terminals),
        "hidden_provider_calls": 0,
        "development_ai_reviews": 0,
        "runtime_workers": WORKERS,
        "answer_workers": WORKERS,
        "inputs_sha256": dg11_state.sha256(INPUTS),
        "new_contexts_sha256": dg11_state.sha256(NEW_CONTEXTS),
        "prior_result_sha256": dg11_state.sha256(PRIOR_RUN / "result.json"),
        "targeted_result_sha256": dg11_state.sha256(TARGETED_RUN / "result.json"),
        "source_identity": source_identity,
        "safety_evidence": safety_evidence,
        "baseline": {
            "dg10": {
                "scorer_v1": dg10_v1,
                "scorer_v2": dg10_v2,
                "stratified_v1": dg10_category_v1,
                "stratified_v2": dg10_category_v2,
            },
            "custom_lexical_top1": {
                "source_arm": "NAIVE_RAG",
                "scorer_v1": lexical_v1,
                "scorer_v2": lexical_v2,
                "stratified_v1": lexical_category_v1,
                "stratified_v2": lexical_category_v2,
            },
        },
        "current": {
            "scorer_v1": current_v1,
            "scorer_v2": current_v2,
            "stratified_v1": current_category_v1,
            "stratified_v2": current_category_v2,
        },
        "summary": summary,
        "gates": gates,
        "records": records,
        "provider_ledger_summary": {
            "event_count": len(ledger),
            "event_counts": dict(event_counts),
            "exact": ledger_exact,
        },
        "finished_at": datetime.now(UTC).isoformat(),
    }
    dg11_state.atomic_json(run_dir / "result.json", result)
    dg11_state.atomic_json(ROOT / "var/dg11/dev/r04-latest-result.json", result)
    dg11_state.append_ledger(
        {
            "run_id": run_id,
            "work_package": "DG11-R04",
            "status": status,
            "decision": result["decision"],
            "provider_requests": len(terminals),
            "development_ai_reviews": 0,
            "metrics": summary,
        }
    )
    state = _load_object(dg11_state.CURRENT_STATE)
    state.setdefault("recovery_work_packages", {})["DG11-R04"] = (
        "PASS" if status == "PASS" else "IN_PROGRESS"
    )
    state["recovery_phase"] = "R04_PASS" if status == "PASS" else "R04_IN_PROGRESS"
    state["latest_result"] = run_id
    state["development_ai_reviews"] = 0
    dg11_state.atomic_json(dg11_state.CURRENT_STATE, state)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run bounded incremental R04 recovery")
    parser.add_argument("run_id")
    args = parser.parse_args()
    started = time.monotonic()
    result = run(args.run_id)
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "decision": result["decision"],
                "provider_requests": result["provider_requests"],
                "protocol": result["protocol"],
                "summary": result["summary"],
                "gates": result["gates"],
                "duration_seconds": round(time.monotonic() - started, 3),
            },
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
