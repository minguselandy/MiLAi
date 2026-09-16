from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
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
from milai.application.query_operators import execute_query_operator
from milai.application.query_planner import QueryPlanner
from milai.domain.retrieval import RetrievalRequest

from evals.benchmark import dg11_holdout, dg11_measurement
from evals.benchmark import lme_product_smoke as benchmark
from scripts import dg11_state
from scripts import run_dg10_benchmark_dev_smoke as scorer_v1

INPUTS = ROOT / "var/dg11/holdout/v1/holdout-inputs.json"
OLD_SCORES = ROOT / "var/dg11/runs/dg11-holdout-20260823-001/scored-records.json"
DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
ENV_FILE = ROOT / "runtime/.env"
PYTHON = ROOT / "runtime/.venv/bin/python"
MCP_PYTHON = ROOT / "integrations/mcp/.venv/bin/python"
ENDPOINT = "http://127.0.0.1:7860"
EXPECTED_CASES = 24
WORKERS = 2
SCOPE = {"project_ids": ["milai"]}

FALSE_ROUTE_FIXTURES = {
    "duration_fact": "How long did it take me to assemble the IKEA bookshelf?",
    "weekday_fact": "Who did I meet with during lunch last Tuesday?",
    "last_weekend_fact": "What game did I finally beat last weekend?",
    "last_trip_percentage": "What percentage of packed shoes did I wear on my last trip?",
    "ordered_list": "What is the order of the events from earliest to latest?",
    "derived_rate": "How many hours do I work in a typical week during peak campaign seasons?",
    "implicit_age_comparison": "How many years older am I than when I graduated?",
    "implicit_quote_comparison": "How much more did I pay after the initial quote?",
    "after_fact": "Where did Rachel move to after her recent relocation?",
    "before_state": "What was my last name before I changed it?",
    "unbounded_event_count": "How many projects did I mention?",
}

TRUE_ROUTE_FIXTURES = {
    "latest": ("What was my latest preference?", "LATEST_VALID_STATE"),
    "scalar_count": ("How many bikes do I own?", "COUNT_DISTINCT"),
    "sum": ("What is the total amount?", "SUM_VALUES"),
    "compare": (
        "What is the difference between the first and second values?",
        "COMPARE_EVENTS",
    ),
    "event_relation": ("What happened before the launch?", "TEMPORAL_BEFORE_AFTER"),
    "distance": (
        "How many days passed between the first event and the second event?",
        "TEMPORAL_DISTANCE",
    ),
}


def _plan(query: str):  # type: ignore[no-untyped-def]
    return QueryPlanner().plan(
        RetrievalRequest(route="L1", query=query, requested_scope=SCOPE)
    )


def _item(value: object, at: str, *, text: str | None = None) -> dict[str, Any]:
    suffix = str(value).replace(" ", "-")
    payload = {"value": value} if text is None else {"memory_text": text}
    return {
        "claim_id": f"claim-{suffix}",
        "claim_version_id": f"version-{suffix}",
        "payload": payload,
        "scope_predicate": SCOPE,
        "valid_time_from": at,
        "evidence_ids": [f"evidence-{suffix}"],
        "open_issue_ids": [],
    }


def _route_checks(cases: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    false_regressions = [
        name for name, query in FALSE_ROUTE_FIXTURES.items() if _plan(query).operator is not None
    ]
    true_regressions = [
        name
        for name, (query, expected) in TRUE_ROUTE_FIXTURES.items()
        if _plan(query).operator != expected
    ]
    records = []
    typed_slot_regressions = []
    for case in cases:
        plan = _plan(str(case["question"]))
        if plan.operator is None:
            continue
        arguments = plan.operator_arguments
        typed = (
            arguments.get("slot_schema_version") == "typed-operator-v1"
            and isinstance(arguments.get("route_reason"), str)
            and bool(arguments.get("route_reason"))
            and isinstance(arguments.get("operand_type"), str)
            and bool(arguments.get("operand_type"))
        )
        if not typed:
            typed_slot_regressions.append(str(case["source_id"]))
        records.append(
            {
                "source_id": str(case["source_id"]),
                "category": str(case["category"]),
                "operator": plan.operator,
                "operator_arguments": arguments,
                "typed_slots_complete": typed,
            }
        )

    wrong_certain = []
    album = execute_query_operator(
        _plan("How many copies of the debut album were released worldwide?"),
        [
            _item(
                "album",
                "2023-05-27T15:55:00+00:00",
                text="The debut album was limited to 500 copies worldwide.",
            )
        ],
    )
    if album is None or album.get("status") != "OK" or album.get("value") != "500":
        wrong_certain.append("scalar_count_value")
    missing_qualifier = execute_query_operator(
        _plan("How many fish are there in my 30-gallon tank?"),
        [
            _item(
                "tank",
                "2023-05-27T15:55:00+00:00",
                text="My 20-gallon tank has ten fish.",
            )
        ],
    )
    if missing_qualifier is None or missing_qualifier.get("status") != "ABSTAINED":
        wrong_certain.append("missing_numeric_qualifier")
    partial_sum = execute_query_operator(
        _plan("What is the total amount?"),
        [_item(10, "2023-05-27T15:55:00+00:00")],
    )
    if partial_sum is None or partial_sum.get("status") != "ABSTAINED":
        wrong_certain.append("partial_sum")
    ambiguous_compare = execute_query_operator(
        _plan("What is the difference between the first and second values?"),
        [
            _item(10, "2023-05-25T15:55:00+00:00"),
            _item(20, "2023-05-26T15:55:00+00:00"),
            _item(30, "2023-05-27T15:55:00+00:00"),
        ],
    )
    if ambiguous_compare is None or ambiguous_compare.get("status") != "ABSTAINED":
        wrong_certain.append("ambiguous_compare")

    summary = {
        "planner_version": QueryPlanner.VERSION,
        "opened_case_count": len(cases),
        "operator_route_count": len(records),
        "known_false_route_regression_count": len(false_regressions),
        "known_false_route_regressions": false_regressions,
        "known_true_route_regression_count": len(true_regressions),
        "known_true_route_regressions": true_regressions,
        "typed_slot_regression_count": len(typed_slot_regressions),
        "typed_slot_regressions": typed_slot_regressions,
        "wrong_certain_operator_fixture_count": len(wrong_certain),
        "wrong_certain_operator_fixtures": wrong_certain,
        "operator_hidden_model_calls": 0,
    }
    return summary, records


def _prepare_contexts(run_dir: Path, cases: list[dict[str, Any]]) -> Path:
    input_path = run_dir / "label-free-inputs.json"
    output_path = run_dir / "contexts.json"
    dg11_state.atomic_json(
        input_path,
        {
            "schema": "milai.dg11.holdout-inputs.v1",
            "label_fields_present": False,
            "source_ids": [case["source_id"] for case in cases],
            "cases": cases,
        },
    )
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
            str(input_path),
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
        ],
        cwd=ROOT,
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("R03 temporal context worker failed")
    return output_path


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
        compiler_version="DG11_R03_QUERY_PLANNER_V7",
    )


def _answers(
    run_id: str,
    run_dir: Path,
    cases: list[dict[str, Any]],
    contexts: dict[str, dict[str, Any]],
    rows: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    case_count = len(cases)
    if case_count < 1:
        raise ValueError("R03 answer execution requires at least one case")
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
            "max_native_requests": case_count,
            "max_prompt_tokens": case_count * benchmark.PROMPT_TOKEN_BUDGET,
            "max_completion_tokens": case_count * benchmark.MAX_OUTPUT_TOKENS,
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
                logical_request_id=f"{run_id}-{index + 1:02d}-r03",
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
            raise RuntimeError("R03 target tokenizer recount differs from native usage")
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

    by_index: dict[int, dict[str, Any]] = {}
    answer_workers = min(WORKERS, case_count)
    with ThreadPoolExecutor(max_workers=answer_workers) as executor:
        pending = {
            executor.submit(answer_one, index, raw_case): index
            for index, raw_case in enumerate(cases)
        }
        for completed_count, future in enumerate(as_completed(pending), start=1):
            by_index[pending[future]] = future.result()
            print(
                json.dumps(
                    {
                        "phase": "answer",
                        "completed": completed_count,
                        "total": case_count,
                        "workers": answer_workers,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    return [by_index[index] for index in range(len(cases))], gateway.read_ledger()


def _f1(records: list[dict[str, Any]]) -> float:
    return round(mean(float(record["scorer_v1"]["normalized_f1"]) for record in records), 6)


def run(run_id: str, *, resume: bool = False) -> dict[str, Any]:
    run_dir = ROOT / "var/dg11/runs" / run_id
    if run_dir.exists():
        if not resume:
            raise FileExistsError(f"R03 run directory already exists: {run_dir}")
        if (run_dir / "result.json").exists() or (run_dir / "provider-ledger.jsonl").exists():
            raise RuntimeError("R03 resume is allowed only before answer generation starts")
    else:
        if resume:
            raise FileNotFoundError(f"R03 resume directory does not exist: {run_dir}")
        run_dir.mkdir(parents=True, exist_ok=False)
    payload = json.loads(INPUTS.read_text(encoding="utf-8"))
    all_cases = list(payload["cases"])
    cases = [case for case in all_cases if case["category"] == "temporal-reasoning"]
    if len(cases) != EXPECTED_CASES:
        raise RuntimeError("R03 temporal denominator drifted")
    route_summary, route_records = _route_checks(all_cases)
    route_gates = {
        "known_false_route_regressions_zero": (
            route_summary["known_false_route_regression_count"] == 0
        ),
        "known_true_route_regressions_zero": (
            route_summary["known_true_route_regression_count"] == 0
        ),
        "typed_slot_regressions_zero": route_summary["typed_slot_regression_count"] == 0,
        "wrong_certain_operator_fixtures_zero": (
            route_summary["wrong_certain_operator_fixture_count"] == 0
        ),
        "operator_hidden_model_calls_zero": (
            route_summary["operator_hidden_model_calls"] == 0
        ),
    }
    dg11_state.atomic_json(
        run_dir / "route-result.json",
        {"summary": route_summary, "gates": route_gates, "records": route_records},
    )
    if not all(route_gates.values()):
        result = {
            "schema": "milai.dg11.r03-operator-gate.v1",
            "run_id": run_id,
            "work_package": "DG11-R03",
            "status": "REVISE",
            "decision": "REVISE_QUERY_PLANNER_BEFORE_TEMPORAL_DEV",
            "provider_requests": 0,
            "hidden_provider_calls": 0,
            "development_ai_reviews": 0,
            "route": route_summary,
            "gates": route_gates,
        }
        dg11_state.atomic_json(run_dir / "result.json", result)
        return result

    context_path = _prepare_contexts(run_dir, cases)
    contexts_payload = json.loads(context_path.read_text(encoding="utf-8"))
    contexts = {str(record["source_id"]): record for record in contexts_payload["records"]}
    source_ids = {str(case["source_id"]) for case in cases}
    rows = {
        str(row["question_id"]): row
        for row in json.loads(DATASET.read_text(encoding="utf-8"))
        if row.get("question_id") in source_ids
    }
    if set(contexts) != source_ids or set(rows) != source_ids:
        raise RuntimeError("R03 context or label identity drifted")
    answers, ledger = _answers(run_id, run_dir, cases, contexts, rows)
    old_payload = json.loads(OLD_SCORES.read_text(encoding="utf-8"))
    old = [
        record
        for record in old_payload["records"]
        if record.get("arm") == "MILAI_DG11_CURRENT"
        and str(record["source_id"]) in source_ids
    ]
    if len(old) != EXPECTED_CASES:
        raise RuntimeError("R03 current DG11 baseline denominator drifted")
    terminals = [event for event in ledger if event.get("event") == "PROVIDER_TERMINAL"]
    posts = [event for event in ledger if event.get("event") == "POST_PROVIDER_TERMINAL"]
    reservations = [event for event in ledger if event.get("event") == "RESERVED"]
    answer_summary = {
        "case_count": len(answers),
        "temporal_current_f1": _f1(answers),
        "temporal_old_dg11_f1": _f1(old),
        "mean_prompt_tokens": round(mean(record["prompt_tokens"] for record in answers), 3),
    }
    gates = {
        **route_gates,
        "temporal_opened_dev_f1_gte_current_dg11": (
            answer_summary["temporal_current_f1"]
            >= answer_summary["temporal_old_dg11_f1"]
        ),
        "provider_denominator_exact": (
            len(reservations) == len(terminals) == len(posts) == EXPECTED_CASES
        ),
        "one_answer_call_per_case": len(answers) == EXPECTED_CASES,
        "hidden_answer_calls_zero": all(record["hidden_model_calls"] == 0 for record in answers),
    }
    status = "PASS" if all(gates.values()) else "REVISE"
    result = {
        "schema": "milai.dg11.r03-operator-gate.v1",
        "run_id": run_id,
        "work_package": "DG11-R03",
        "status": status,
        "decision": "KEEP_QUERY_PLANNER_V7" if status == "PASS" else "REVISE_QUERY_PLANNER_V7",
        "provider_requests": len(terminals),
        "hidden_provider_calls": 0,
        "development_ai_reviews": 0,
        "route": route_summary,
        "answer": answer_summary,
        "gates": gates,
        "records": {"route": route_records, "answer": answers},
        "finished_at": datetime.now(UTC).isoformat(),
    }
    dg11_state.atomic_json(run_dir / "result.json", result)
    dg11_state.atomic_json(ROOT / "var/dg11/dev/latest-result.json", result)
    dg11_state.append_ledger(
        {
            "run_id": run_id,
            "work_package": "DG11-R03",
            "status": status,
            "decision": result["decision"],
            "provider_requests": len(terminals),
            "development_ai_reviews": 0,
            "metrics": {"route": route_summary, "answer": answer_summary},
        }
    )
    state = json.loads(dg11_state.CURRENT_STATE.read_text(encoding="utf-8"))
    state.setdefault("recovery_work_packages", {})["DG11-R03"] = (
        "PASS" if status == "PASS" else "IN_PROGRESS"
    )
    state["recovery_phase"] = "R03_PASS" if status == "PASS" else "R03_IN_PROGRESS"
    state["latest_result"] = run_id
    state["development_ai_reviews"] = 0
    dg11_state.atomic_json(dg11_state.CURRENT_STATE, state)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
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
                "route": result["route"],
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
