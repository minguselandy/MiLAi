from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
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

INPUTS = ROOT / "var/dg11/holdout/v1/holdout-inputs.json"
BASELINES = ROOT / "var/dg11/runs/dg11-holdout-20260823-001/scored-records.json"
DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
ENV_FILE = ROOT / "runtime/.env"
PYTHON = ROOT / "runtime/.venv/bin/python"
MCP_PYTHON = ROOT / "integrations/mcp/.venv/bin/python"
ENDPOINT = "http://127.0.0.1:7860"
EXPECTED_CASES = 100
WORKERS = 2
GENERATION_NAMESPACE = "dg11-r04-combined-dev2-v1"

R02_RESULT = ROOT / "var/dg11/runs/dg11-r02-production-20260823-002/result.json"
R03_RESULT = ROOT / "var/dg11/runs/dg11-r03-operator-20260823-005/result.json"
FUNCTIONAL_RESULT = ROOT / "var/dg11/functional/latest-result.json"
AGENTIC_RESULT = ROOT / "var/dg11/agentic/latest-result.json"

SOURCE_IDENTITY_PATHS = (
    ROOT / "scripts/run_dg11_r04_combined_dev2.py",
    ROOT / "evals/benchmark/dg11_holdout_context_worker.py",
    ROOT / "evals/benchmark/lme_product_smoke.py",
    ROOT / "runtime/src/milai/adapters/agent_prefetch.py",
    ROOT / "runtime/src/milai/adapters/provider_execution.py",
    ROOT / "runtime/src/milai/api/app.py",
    ROOT / "runtime/src/milai/application/query_operators.py",
    ROOT / "runtime/src/milai/application/query_planner.py",
    ROOT / "runtime/src/milai/application/retrieval.py",
    ROOT / "runtime/src/milai/config/settings.py",
    ROOT / "runtime/src/milai/operations/smoke.py",
    ROOT / "runtime/.env",
)


class R04Error(RuntimeError):
    pass


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise R04Error(f"expected JSON object: {path}")
    return value


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _aggregate(records: Sequence[Mapping[str, Any]], scorer: str) -> dict[str, Any]:
    if not records:
        raise R04Error("cannot aggregate an empty record group")
    return {
        "case_count": len(records),
        "exact_match_mean": round(
            mean(float(record[scorer]["exact_match"]) for record in records), 6
        ),
        "normalized_f1_mean": round(
            mean(float(record[scorer]["normalized_f1"]) for record in records), 6
        ),
    }


def _stratified(
    records: Sequence[Mapping[str, Any]], scorer: str
) -> dict[str, dict[str, Any]]:
    grouped: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["category"])].append(record)
    return {
        category: _aggregate(group, scorer)
        for category, group in sorted(grouped.items())
    }


def _arm_records(
    payload: Mapping[str, Any], arm: str, source_ids: set[str]
) -> list[dict[str, Any]]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise R04Error("baseline records are absent")
    selected = [
        dict(record)
        for record in records
        if isinstance(record, Mapping)
        and record.get("arm") == arm
        and str(record.get("source_id")) in source_ids
    ]
    if (
        len(selected) != EXPECTED_CASES
        or {str(record["source_id"]) for record in selected} != source_ids
    ):
        raise R04Error(f"{arm} baseline denominator drifted")
    return selected


def _safety_evidence() -> tuple[bool, dict[str, Any]]:
    r02 = _load_object(R02_RESULT)
    r03 = _load_object(R03_RESULT)
    functional = _load_object(FUNCTIONAL_RESULT)
    agentic = _load_object(AGENTIC_RESULT)
    r02_gates = _mapping(r02.get("gates"))
    r03_gates = _mapping(r03.get("gates"))
    functional_classification = _mapping(functional.get("classification"))
    functional_gates = _mapping(functional_classification.get("gates"))
    agentic_gates = _mapping(agentic.get("gates"))
    checks = {
        "r02_retrieval_degraded_cases_zero": (
            r02.get("status") == "PASS"
            and r02_gates.get("retrieval_degraded_cases_zero") is True
            and r02_gates.get("hidden_answer_calls_zero") is True
        ),
        "r03_wrong_certain_and_route_regressions_zero": (
            r03.get("status") == "PASS"
            and r03_gates.get("wrong_certain_operator_fixtures_zero") is True
            and r03_gates.get("known_false_route_regressions_zero") is True
            and r03_gates.get("operator_hidden_model_calls_zero") is True
        ),
        "functional_canonical_and_secret_gates_pass": (
            functional.get("status") == "PASS"
            and functional_gates.get("canonical_mutation_semantics_unchanged") is True
            and functional_gates.get("secret_private_content_leakage_zero") is True
        ),
        "agentic_wrong_certain_and_stale_actions_zero": (
            agentic.get("status") == "PASS"
            and agentic_gates.get("wrong_certain_actions_zero") is True
            and agentic_gates.get("stale_revoked_actions_zero") is True
        ),
    }
    artifacts = {
        name: {
            "path": str(path.relative_to(ROOT)),
            "sha256": dg11_state.sha256(path),
        }
        for name, path in {
            "r02": R02_RESULT,
            "r03": R03_RESULT,
            "functional": FUNCTIONAL_RESULT,
            "agentic": AGENTIC_RESULT,
        }.items()
    }
    return all(checks.values()), {"checks": checks, "artifacts": artifacts}


def _evaluate_quality_gates(
    *,
    current_v1: Mapping[str, Any],
    dg10_v1: Mapping[str, Any],
    current_categories: Mapping[str, Mapping[str, Any]],
    dg10_categories: Mapping[str, Mapping[str, Any]],
    lexical_categories: Mapping[str, Mapping[str, Any]],
    mean_memory_tokens: float,
    safety_pass: bool,
) -> dict[str, bool]:
    f1_delta = round(
        float(current_v1["normalized_f1_mean"]) - float(dg10_v1["normalized_f1_mean"]),
        6,
    )
    em_delta = round(
        float(current_v1["exact_match_mean"]) - float(dg10_v1["exact_match_mean"]),
        6,
    )
    multi_delta = round(
        float(current_categories["multi-session"]["normalized_f1_mean"])
        - float(dg10_categories["multi-session"]["normalized_f1_mean"]),
        6,
    )
    assistant_delta = round(
        float(current_categories["single-session-assistant"]["normalized_f1_mean"])
        - float(lexical_categories["single-session-assistant"]["normalized_f1_mean"]),
        6,
    )
    knowledge_delta = round(
        float(current_categories["knowledge-update"]["normalized_f1_mean"])
        - float(dg10_categories["knowledge-update"]["normalized_f1_mean"]),
        6,
    )
    return {
        "f1_vs_dg10_gte_plus_0_05": f1_delta >= 0.05,
        "em_vs_dg10_gte_zero": em_delta >= 0,
        "multi_session_vs_dg10_gte_zero": multi_delta >= 0,
        "single_assistant_vs_custom_lexical_gte_zero": assistant_delta >= 0,
        "knowledge_update_regression_gte_minus_0_02": knowledge_delta >= -0.02,
        "mean_memory_tokens_lte_320": mean_memory_tokens <= 320,
        "safety_regressions_zero": safety_pass,
    }


def _context(value: Mapping[str, Any]) -> PrefetchContext:
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
        compiler_version=str(value.get("compiler_version") or "UNRECORDED"),
    )


def _prepare_contexts(run_dir: Path) -> Path:
    output_path = run_dir / "contexts.json"
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
    completed = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "evals.benchmark.dg11_holdout_context_worker",
            "--inputs",
            str(run_dir / "label-free-inputs.json"),
            "--output",
            str(output_path),
            "--env-file",
            str(ENV_FILE),
            "--identity",
            "current",
            "--workers",
            str(WORKERS),
            "--expected-cases",
            str(EXPECTED_CASES),
            "--recall-limit",
            "3",
            "--max-case-attempts",
            "3",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        raise R04Error("R04 context worker failed; resume from its checkpoint")
    return output_path


def _source_identity() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): dg11_state.sha256(path)
        for path in SOURCE_IDENTITY_PATHS
    }


def run(run_id: str, *, resume: bool = False) -> dict[str, Any]:
    run_dir = ROOT / "var/dg11/runs" / run_id
    if run_dir.exists():
        if not resume:
            raise FileExistsError(f"R04 run directory already exists: {run_dir}")
        if (run_dir / "result.json").exists() or (
            run_dir / "provider-ledger.jsonl"
        ).exists():
            raise R04Error("R04 resume is allowed only before answer generation starts")
    else:
        if resume:
            raise FileNotFoundError(f"R04 resume directory does not exist: {run_dir}")
        run_dir.mkdir(parents=True, exist_ok=False)

    input_payload = _load_object(INPUTS)
    cases = input_payload.get("cases")
    if (
        input_payload.get("schema") != "milai.dg11.holdout-inputs.v1"
        or input_payload.get("label_fields_present") is not False
        or not isinstance(cases, list)
        or len(cases) != EXPECTED_CASES
    ):
        raise R04Error("R04 label-free input denominator drifted")
    local_inputs = run_dir / "label-free-inputs.json"
    if not local_inputs.exists():
        dg11_state.atomic_json(local_inputs, input_payload)
    elif _load_object(local_inputs) != input_payload:
        raise R04Error("R04 resumed input package drifted")
    raw_cases = [dict(case) for case in cases if isinstance(case, Mapping)]
    source_ids = {str(case["source_id"]) for case in raw_cases}
    if len(raw_cases) != EXPECTED_CASES or len(source_ids) != EXPECTED_CASES:
        raise R04Error("R04 source IDs drifted")

    safety_pass, safety_evidence = _safety_evidence()
    source_identity = _source_identity()
    context_path = _prepare_contexts(run_dir)
    contexts_payload = _load_object(context_path)
    context_records = contexts_payload.get("records")
    if not isinstance(context_records, list):
        raise R04Error("R04 contexts are absent")
    contexts = {
        str(record["source_id"]): dict(record)
        for record in context_records
        if isinstance(record, Mapping)
    }
    if set(contexts) != source_ids:
        raise R04Error("R04 context denominator drifted")
    if _source_identity() != source_identity:
        raise R04Error("R04 source identity changed during context generation")

    prepared: list[dict[str, Any]] = []
    for raw_case in raw_cases:
        source_id = str(raw_case["source_id"])
        case = dg11_holdout.product_case(raw_case)
        context_record = contexts[source_id]
        raw_context = context_record.get("context")
        if not isinstance(raw_context, Mapping):
            raise R04Error(f"R04 context is invalid: {source_id}")
        context = _context(raw_context)
        messages = benchmark._messages(case.question, case.question_at, context)
        no_memory_messages = benchmark._messages(
            case.question,
            case.question_at,
            PrefetchContext.no_memory(),
        )
        prompt_tokens = benchmark._count_prompt_tokens(ENDPOINT, messages)
        no_memory_tokens = benchmark._count_prompt_tokens(ENDPOINT, no_memory_messages)
        memory_tokens = max(0, prompt_tokens - no_memory_tokens)
        if memory_tokens > benchmark.MEMORY_TOKEN_BUDGET:
            raise R04Error(f"{source_id} exceeds the 512-token memory ceiling")
        prepared.append(
            {
                "source_id": source_id,
                "raw_case": raw_case,
                "case": case,
                "context": context,
                "messages": messages,
                "prompt_tokens": prompt_tokens,
                "memory_tokens": memory_tokens,
                "trace": context_record.get("trace"),
            }
        )

    dataset_rows = json.loads(DATASET.read_text(encoding="utf-8"))
    rows = {
        str(row["question_id"]): row
        for row in dataset_rows
        if isinstance(row, dict) and str(row.get("question_id")) in source_ids
    }
    if set(rows) != source_ids:
        raise R04Error("R04 scorer rows drifted")

    baseline_payload = _load_object(BASELINES)
    dg10 = _arm_records(baseline_payload, "MILAI_DG10_FROZEN", source_ids)
    lexical = _arm_records(baseline_payload, "NAIVE_RAG", source_ids)

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
            "dataset_manifest_sha256": dg11_state.sha256(local_inputs),
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

    def answer_one(index: int, item: Mapping[str, Any]) -> dict[str, Any]:
        source_id = str(item["source_id"])
        call_started = time.perf_counter()
        completion = gateway.execute(
            ProviderRequest(
                logical_request_id=f"{run_id}-{index + 1:03d}-combined",
                transport="json",
                payload=benchmark._payload(
                    cast(list[dict[str, str]], item["messages"]),
                    f"{GENERATION_NAMESPACE}-{index + 1:03d}",
                ),
                prompt_token_budget=benchmark.PROMPT_TOKEN_BUDGET,
                completion_token_budget=benchmark.MAX_OUTPUT_TOKENS,
                timeout_seconds=180,
            ),
            transport,
            benchmark._parse,
        )
        if completion.prompt_tokens != item["prompt_tokens"]:
            raise R04Error("R04 target tokenizer recount differs from native usage")
        answer = scorer_v1._parse_answer(completion.value)
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
            "context_chars": len(context.rendered),
            "memory_tokens": item["memory_tokens"],
            "prompt_tokens": item["prompt_tokens"],
            "completion_tokens": completion.completion_tokens,
            "retrieved_session_ids": retrieved,
            "retrieval_hit_at_3": int(bool(hits)),
            "relevant_coverage_at_3": (
                round(len(hits) / len(answer_sessions), 6) if answer_sessions else 0.0
            ),
            "answer_span_present": dg11_measurement.answer_span_present(
                context.rendered, labels
            ),
            "runtime_trace": trace,
            "answer_latency_ms": round((time.perf_counter() - call_started) * 1000, 3),
            "native_request_id": completion.native_request_id,
            "model_calls": 1,
            "hidden_model_calls": 0,
        }

    by_index: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(
        max_workers=WORKERS, thread_name_prefix="dg11-r04-answer"
    ) as pool:
        pending = {
            pool.submit(answer_one, index, item): index
            for index, item in enumerate(prepared)
        }
        for completed_count, future in enumerate(as_completed(pending), start=1):
            by_index[pending[future]] = future.result()
            print(
                json.dumps(
                    {
                        "phase": "answer",
                        "completed": completed_count,
                        "total": EXPECTED_CASES,
                        "workers": WORKERS,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    records = [by_index[index] for index in range(EXPECTED_CASES)]
    ledger = gateway.read_ledger()
    event_counts = Counter(str(event.get("event")) for event in ledger)
    terminals = [event for event in ledger if event.get("event") == "PROVIDER_TERMINAL"]
    ledger_exact = (
        event_counts["RESERVED"]
        == event_counts["PROVIDER_TERMINAL"]
        == event_counts["POST_PROVIDER_TERMINAL"]
        == EXPECTED_CASES
        and all(event.get("status") == "SUCCEEDED" for event in terminals)
        and len({event.get("logical_request_id") for event in terminals})
        == EXPECTED_CASES
        and len({event.get("native_request_id") for event in terminals})
        == EXPECTED_CASES
    )

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
    memory_tokens_mean = round(mean(record["memory_tokens"] for record in records), 3)
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
        "provider_denominator_exact": ledger_exact,
        "one_answer_call_per_case": len(records) == EXPECTED_CASES,
        "hidden_answer_calls_zero": all(
            record["hidden_model_calls"] == 0 for record in records
        ),
        "memory_token_ceiling_512": max(record["memory_tokens"] for record in records)
        <= benchmark.MEMORY_TOKEN_BUDGET,
        "context_denominator_exact": len(contexts) == EXPECTED_CASES,
        "source_identity_stable": _source_identity() == source_identity,
    }
    gates = {**quality_gates, **execution_gates}
    status = "PASS" if all(gates.values()) else "REVISE"
    result = {
        "schema": "milai.dg11.r04-combined-dev2.v1",
        "run_id": run_id,
        "work_package": "DG11-R04",
        "status": status,
        "decision": "KEEP_COMBINED_DEV2"
        if status == "PASS"
        else "REVISE_COMBINED_DEV2",
        "case_denominator": EXPECTED_CASES,
        "provider_requests": len(terminals),
        "hidden_provider_calls": 0,
        "development_ai_reviews": 0,
        "runtime_workers": WORKERS,
        "answer_workers": WORKERS,
        "inputs_sha256": dg11_state.sha256(local_inputs),
        "baseline_sha256": dg11_state.sha256(BASELINES),
        "dataset_sha256": dg11_state.sha256(DATASET),
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
        "summary": {
            "f1_delta_vs_dg10": round(
                current_v1["normalized_f1_mean"] - dg10_v1["normalized_f1_mean"],
                6,
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
            "memory_tokens_max": max(record["memory_tokens"] for record in records),
            "retrieval_hit_at_3": round(
                mean(record["retrieval_hit_at_3"] for record in records), 6
            ),
            "relevant_coverage_at_3": round(
                mean(record["relevant_coverage_at_3"] for record in records), 6
            ),
            "answer_span_survival": round(
                mean(bool(record["answer_span_present"]) for record in records), 6
            ),
        },
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
            "metrics": result["summary"],
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
    parser = argparse.ArgumentParser(
        description="Run the 100-case DG11-R04 Combined DEV-2"
    )
    parser.add_argument("run_id")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    result = run(args.run_id, resume=args.resume)
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "decision": result["decision"],
                "provider_requests": result["provider_requests"],
                "summary": result["summary"],
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
