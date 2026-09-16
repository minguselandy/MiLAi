from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

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

TARGET_SOURCE_IDS = ("45dc21b6", "830ce83f", "e493bb7c")
INPUTS = ROOT / "var/dg11/holdout/v1/holdout-inputs.json"
DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
PRIOR_R04 = ROOT / "var/dg11/runs/dg11-r04-combined-dev2-20260823-001/result.json"
CONTEXT_PATHS = (
    ROOT
    / "var/dg11/runs/dg11-r04-recovery-contexts-20260823-002/count-contexts.json",
    ROOT
    / "var/dg11/runs/dg11-r04-recovery-contexts-20260823-003/state-contexts.json",
)
ENDPOINT = "http://127.0.0.1:7860"
WORKERS = 2
GENERATION_NAMESPACE = "dg11-r04-targeted-recheck-v1"
SOURCE_PATHS = (
    ROOT / "scripts/run_dg11_r04_targeted_recheck.py",
    ROOT / "runtime/src/milai/adapters/agent_prefetch.py",
    ROOT / "runtime/src/milai/application/query_operators.py",
    ROOT / "runtime/src/milai/application/query_planner.py",
    ROOT / "runtime/src/milai/application/retrieval.py",
    ROOT / "runtime/.env",
)


class TargetedRecheckError(RuntimeError):
    pass


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TargetedRecheckError(f"expected object: {path}")
    return value


def _context(value: Mapping[str, Any]) -> PrefetchContext:
    return PrefetchContext(
        status=cast(
            Literal["NO_MEMORY", "AVAILABLE", "UNCERTAIN", "UNAVAILABLE"],
            value["status"],
        ),
        rendered=str(value["rendered"]),
        context_sha256=str(value["context_sha256"]),
        trace_id=None,
        request_id=None,
        claim_refs=(),
        evidence_refs=(),
        open_issue_ids=(),
        degraded_components=(),
        abstention_reason=None,
        compiler_version=str(value["compiler_version"]),
    )


def run(run_id: str) -> dict[str, Any]:
    run_dir = ROOT / "var/dg11/runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    input_payload = _object(INPUTS)
    raw_cases = {
        str(value["source_id"]): dict(value)
        for value in input_payload.get("cases", [])
        if isinstance(value, Mapping)
        and str(value.get("source_id")) in TARGET_SOURCE_IDS
    }
    if set(raw_cases) != set(TARGET_SOURCE_IDS):
        raise TargetedRecheckError("target label-free cases are incomplete")

    context_records: dict[str, dict[str, Any]] = {}
    context_artifacts: dict[str, str] = {}
    for path in CONTEXT_PATHS:
        payload = _object(path)
        context_artifacts[str(path.relative_to(ROOT))] = dg11_state.sha256(path)
        for value in payload.get("records", []):
            if isinstance(value, Mapping) and str(value.get("source_id")) in TARGET_SOURCE_IDS:
                context_records[str(value["source_id"])] = dict(value)
    if set(context_records) != set(TARGET_SOURCE_IDS):
        raise TargetedRecheckError("target contexts are incomplete")

    prepared: list[dict[str, Any]] = []
    for source_id in TARGET_SOURCE_IDS:
        case = dg11_holdout.product_case(raw_cases[source_id])
        raw_context = context_records[source_id].get("context")
        if not isinstance(raw_context, Mapping):
            raise TargetedRecheckError(f"invalid context: {source_id}")
        context = _context(raw_context)
        if context.status != "AVAILABLE" or context.compiler_version != "DG11_GROUPED_COMPACT_V3":
            raise TargetedRecheckError(f"target context is not answerable: {source_id}")
        messages = benchmark._messages(case.question, case.question_at, context)
        prompt_tokens = benchmark._count_prompt_tokens(ENDPOINT, messages)
        no_memory_tokens = benchmark._count_prompt_tokens(
            ENDPOINT,
            benchmark._messages(case.question, case.question_at, PrefetchContext.no_memory()),
        )
        memory_tokens = max(0, prompt_tokens - no_memory_tokens)
        if memory_tokens > benchmark.MEMORY_TOKEN_BUDGET:
            raise TargetedRecheckError(f"memory token ceiling exceeded: {source_id}")
        prepared.append(
            {
                "source_id": source_id,
                "case": case,
                "context": context,
                "messages": messages,
                "prompt_tokens": prompt_tokens,
                "memory_tokens": memory_tokens,
                "trace": context_records[source_id].get("trace"),
            }
        )

    rows = {
        str(row["question_id"]): row
        for row in json.loads(DATASET.read_text(encoding="utf-8"))
        if isinstance(row, dict) and str(row.get("question_id")) in TARGET_SOURCE_IDS
    }
    if set(rows) != set(TARGET_SOURCE_IDS):
        raise TargetedRecheckError("target labels are incomplete")

    manifest_path = run_dir / "provider-manifest.json"
    ledger_path = run_dir / "provider-ledger.jsonl"
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
            "prompt_template_sha256": benchmark.prompt_contract_sha256(),
            "max_native_requests": len(TARGET_SOURCE_IDS),
            "max_prompt_tokens": len(TARGET_SOURCE_IDS) * benchmark.PROMPT_TOKEN_BUDGET,
            "max_completion_tokens": len(TARGET_SOURCE_IDS) * benchmark.MAX_OUTPUT_TOKENS,
            "deadline": (now + timedelta(minutes=10)).isoformat(),
            "expires_at": (now + timedelta(minutes=15)).isoformat(),
            "synthetic_or_deidentified_only": True,
            "closed_test_access": False,
        },
    )
    gateway = ProviderExecutionGateway(manifest_path, ledger_path)
    transport = JsonCompletionTransport()

    def answer_one(index: int, item: Mapping[str, Any]) -> dict[str, Any]:
        source_id = str(item["source_id"])
        completion = gateway.execute(
            ProviderRequest(
                logical_request_id=f"{run_id}-{index + 1:02d}-targeted",
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
            raise TargetedRecheckError("native tokenizer recount drifted")
        answer = scorer_v1._parse_answer(completion.value)
        labels = benchmark.scoring._answer_values(rows[source_id]["answer"])
        context = cast(PrefetchContext, item["context"])
        return {
            "source_id": source_id,
            "answer": answer,
            "scorer_v1": scorer_v1._score(answer, labels),
            "scorer_v2": dg11_measurement.score_v2(answer, labels),
            "answer_span_present": dg11_measurement.answer_span_present(
                context.rendered, labels
            ),
            "context_sha256": context.context_sha256,
            "compiler_version": context.compiler_version,
            "memory_tokens": item["memory_tokens"],
            "prompt_tokens": item["prompt_tokens"],
            "completion_tokens": completion.completion_tokens,
            "native_request_id": completion.native_request_id,
            "runtime_trace": item["trace"],
            "model_calls": 1,
            "hidden_model_calls": 0,
        }

    by_index: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="r04-targeted") as pool:
        pending = {
            pool.submit(answer_one, index, item): index
            for index, item in enumerate(prepared)
        }
        for completed, future in enumerate(as_completed(pending), start=1):
            by_index[pending[future]] = future.result()
            print(
                json.dumps(
                    {"phase": "answer", "completed": completed, "total": 3, "workers": 2},
                    sort_keys=True,
                ),
                flush=True,
            )
    records = [by_index[index] for index in range(len(prepared))]

    events = gateway.read_ledger()
    event_counts = Counter(str(event.get("event")) for event in events)
    terminals = [event for event in events if event.get("event") == "PROVIDER_TERMINAL"]
    ledger_exact = (
        event_counts["RESERVED"]
        == event_counts["PROVIDER_TERMINAL"]
        == event_counts["POST_PROVIDER_TERMINAL"]
        == len(TARGET_SOURCE_IDS)
        and all(event.get("status") == "SUCCEEDED" for event in terminals)
    )

    prior = _object(PRIOR_R04)
    prior_records = [
        value for value in prior.get("records", []) if isinstance(value, Mapping)
    ]
    old_scores = {
        str(value["source_id"]): float(value["scorer_v1"]["normalized_f1"])
        for value in prior_records
    }
    new_scores = {
        str(value["source_id"]): float(value["scorer_v1"]["normalized_f1"])
        for value in records
    }
    projected_overall = (
        sum(old_scores.values())
        - sum(old_scores[source_id] for source_id in TARGET_SOURCE_IDS)
        + sum(new_scores.values())
    ) / len(prior_records)
    knowledge_ids = {
        str(value["source_id"])
        for value in prior_records
        if value.get("category") == "knowledge-update"
    }
    projected_knowledge = (
        sum(old_scores[source_id] for source_id in knowledge_ids)
        - sum(old_scores[source_id] for source_id in TARGET_SOURCE_IDS)
        + sum(new_scores.values())
    ) / len(knowledge_ids)
    dg10_overall = float(prior["baseline"]["dg10"]["scorer_v1"]["normalized_f1_mean"])
    dg10_knowledge = float(
        prior["baseline"]["dg10"]["stratified_v1"]["knowledge-update"][
            "normalized_f1_mean"
        ]
    )
    projection = {
        "f1_delta_vs_dg10": round(projected_overall - dg10_overall, 6),
        "knowledge_update_f1_delta_vs_dg10": round(
            projected_knowledge - dg10_knowledge, 6
        ),
    }
    gates = {
        "provider_ledger_exact": ledger_exact,
        "target_answers_exact": all(
            float(value["scorer_v1"]["exact_match"]) == 1.0 for value in records
        ),
        "target_answer_spans_present": all(
            value["answer_span_present"] is True for value in records
        ),
        "projected_r04_f1_gate": projection["f1_delta_vs_dg10"] >= 0.05,
        "projected_knowledge_update_gate": (
            projection["knowledge_update_f1_delta_vs_dg10"] >= -0.02
        ),
        "hidden_model_calls_zero": all(value["hidden_model_calls"] == 0 for value in records),
    }
    result = {
        "schema": "milai.dg11.r04-targeted-recheck.v1",
        "run_id": run_id,
        "status": "PASS" if all(gates.values()) else "REVISE",
        "target_source_ids": list(TARGET_SOURCE_IDS),
        "provider_requests": len(terminals),
        "answer_workers": WORKERS,
        "development_ai_reviews": 0,
        "context_artifacts": context_artifacts,
        "source_identity": {
            str(path.relative_to(ROOT)): dg11_state.sha256(path) for path in SOURCE_PATHS
        },
        "projection_only_not_full_r04": True,
        "projected_r04": projection,
        "gates": gates,
        "records": records,
        "provider_ledger_summary": {
            "event_count": len(events),
            "event_counts": dict(event_counts),
            "exact": ledger_exact,
        },
        "finished_at": datetime.now(UTC).isoformat(),
    }
    dg11_state.atomic_json(run_dir / "result.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the three-case R04 recovery recheck")
    parser.add_argument("run_id")
    args = parser.parse_args()
    started = time.monotonic()
    result = run(args.run_id)
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "provider_requests": result["provider_requests"],
                "projected_r04": result["projected_r04"],
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
