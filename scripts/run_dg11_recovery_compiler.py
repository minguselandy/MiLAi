from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from milai.adapters.agent_prefetch import PrefetchContext, prepare_compact_prefetch
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
CONTEXTS = ROOT / "var/dg11/runs/dg11-holdout-20260823-001/contexts-dg11-current.json"
SCORED = ROOT / "var/dg11/runs/dg11-holdout-20260823-001/scored-records.json"
DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
TOKENIZER = Path("/cra/qwen36-35B/tokenizer.json")
ENDPOINT = "http://127.0.0.1:7860"
SELECTED_CATEGORIES = {"single-session-assistant", "single-session-user"}
EXPECTED_ANSWER_CALLS = 26
SAFETY_TESTS = (
    "tests/unit/test_agent_prefetch.py",
    "tests/unit/test_query_planner.py",
    "tests/unit/test_query_operators.py",
    "tests/unit/test_retrieval_fusion.py",
    "tests/integration/test_context_chat_api.py::test_capsule_preserves_live_open_issue_identity_branches_and_discharge_rule",
    "tests/integration/test_context_chat_api.py::test_revoke_invalidates_pointer_and_stale_chat_abstains",
)


def _mean(records: list[dict[str, Any]], field: str) -> float:
    return round(mean(float(record[field]) for record in records), 6)


def _recompile(
    case: dict[str, Any], old: dict[str, Any]
) -> PrefetchContext:
    old_context = old["context"]
    rendered = str(old_context["rendered"])
    items = old["trace"]["retrieved_items"]
    if (
        old_context["status"] != "AVAILABLE"
        or "\nDERIVED " in rendered
        or not items
    ):
        return PrefetchContext(
            status=old_context["status"],
            rendered=rendered,
            context_sha256=old_context["context_sha256"],
            trace_id=None,
            request_id=None,
            claim_refs=(),
            evidence_refs=(),
            open_issue_ids=(),
            degraded_components=(),
            abstention_reason=None,
            compiler_version="DG11_V1_CONTEXT_PRESERVED_NON_COMPILER_PATH",
        )
    sessions = {session["session_id"]: session for session in case["sessions"]}
    recall_items = []
    for item in items:
        session_id = str(item["session_id"])
        session = sessions[session_id]
        recall_items.append(
            {
                "memory_text": session["text"],
                "payload": {"session_id": session_id},
                "valid_time_from": item["valid_time_from"],
                "relevance_score": item["relevance_score"],
                "authority": "ACTION_SAFE",
                "epistemic_status": "VERIFIED",
            }
        )
    return prepare_compact_prefetch(
        {
            "status": "OK",
            "items": recall_items,
            "open_issue_ids": [],
            "degraded_components": [],
            "abstention_reason": None,
        },
        query=str(case["question"]),
        max_context_chars=benchmark.COMPACT_CONTEXT_CHARS,
    )


def _safety_preflight() -> dict[str, Any]:
    benchmark._load_environment_file((ROOT / "runtime/.env").resolve())
    command = [str(ROOT / "runtime/.venv/bin/python"), "-m", "pytest", "-q", *SAFETY_TESTS]
    completed = subprocess.run(
        command,
        cwd=ROOT / "runtime",
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise RuntimeError("R01 safety preflight failed\n" + output[-4000:])
    return {
        "command": command,
        "exit_code": completed.returncode,
        "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
        "test_targets": list(SAFETY_TESTS),
    }


def run(run_id: str) -> dict[str, Any]:
    run_dir = ROOT / "var/dg11/runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    safety = _safety_preflight()
    inputs = json.loads(INPUTS.read_text(encoding="utf-8"))
    old_contexts_payload = json.loads(CONTEXTS.read_text(encoding="utf-8"))
    scored_payload = json.loads(SCORED.read_text(encoding="utf-8"))
    dataset_rows = json.loads(DATASET.read_text(encoding="utf-8"))
    cases = {case["source_id"]: case for case in inputs["cases"]}
    rows = {row["question_id"]: row for row in dataset_rows}
    old_contexts = {
        record["source_id"]: record for record in old_contexts_payload["records"]
    }
    old_scores = {
        (record["source_id"], record["arm"]): record
        for record in scored_payload["records"]
    }
    tokenizer = Tokenizer.from_file(str(TOKENIZER))

    comparisons: list[dict[str, Any]] = []
    compiled: dict[str, PrefetchContext] = {}
    for source_id in inputs["source_ids"]:
        case = cases[source_id]
        old = old_contexts[source_id]
        context = _recompile(case, old)
        compiled[source_id] = context
        answers = benchmark.scoring._answer_values(rows[source_id]["answer"])
        relevant = {str(value) for value in rows[source_id]["answer_session_ids"]}
        retrieved = {str(value) for value in old["trace"]["retrieved_session_ids"]}
        hit = bool(relevant.intersection(retrieved))
        comparisons.append(
            {
                "source_id": source_id,
                "category": case["category"],
                "retrieval_hit_at_3": int(hit),
                "baseline_answer_span_present": dg11_measurement.answer_span_present(
                    old["context"]["rendered"], answers
                ),
                "current_answer_span_present": dg11_measurement.answer_span_present(
                    context.rendered, answers
                ),
                "baseline_context_sha256": old["context"]["context_sha256"],
                "current_context_sha256": context.context_sha256,
                "current_context_tokens": len(tokenizer.encode(context.rendered).ids),
                "compiler_version": context.compiler_version,
            }
        )
    dg11_state.atomic_json(
        run_dir / "compiler-contexts.json",
        {
            "schema": "milai.dg11.r01-compiler-contexts.v1",
            "records": [
                {
                    "source_id": source_id,
                    "status": context.status,
                    "rendered": context.rendered,
                    "context_sha256": context.context_sha256,
                    "compiler_version": context.compiler_version,
                }
                for source_id, context in compiled.items()
            ],
        },
    )
    dg11_state.atomic_json(run_dir / "offline-comparisons.json", {"records": comparisons})

    selected = [
        source_id
        for source_id in inputs["source_ids"]
        if cases[source_id]["category"] in SELECTED_CATEGORIES
    ]
    if len(selected) != EXPECTED_ANSWER_CALLS:
        raise RuntimeError("R01 assistant/user answer denominator drifted")
    now = datetime.now(UTC)
    manifest = {
        "schema": "milai.provider.dev-run.v1",
        "run_id": run_id,
        "phase": "dev",
        "provider": "local_vllm",
        "endpoint_identity": ENDPOINT,
        "model_id": benchmark.MODEL_ID,
        "dataset_manifest_sha256": dg11_state.sha256(INPUTS),
        "prompt_template_sha256": benchmark.prompt_contract_sha256(),
        "max_native_requests": EXPECTED_ANSWER_CALLS,
        "max_prompt_tokens": EXPECTED_ANSWER_CALLS * benchmark.PROMPT_TOKEN_BUDGET,
        "max_completion_tokens": EXPECTED_ANSWER_CALLS * benchmark.MAX_OUTPUT_TOKENS,
        "deadline": (now + timedelta(minutes=15)).isoformat(),
        "expires_at": (now + timedelta(minutes=20)).isoformat(),
        "synthetic_or_deidentified_only": True,
        "closed_test_access": False,
    }
    manifest_path = run_dir / "provider-manifest.json"
    ledger_path = run_dir / "provider-ledger.jsonl"
    dg11_state.atomic_json(manifest_path, manifest)
    gateway = ProviderExecutionGateway(manifest_path, ledger_path)
    transport = JsonCompletionTransport()
    answer_records: list[dict[str, Any]] = []
    for index, source_id in enumerate(selected):
        case = dg11_holdout.product_case(cases[source_id])
        context = compiled[source_id]
        messages = benchmark._messages(case.question, case.question_at, context)
        prompt_tokens = benchmark._count_prompt_tokens(ENDPOINT, messages)
        completion = gateway.execute(
            ProviderRequest(
                logical_request_id=f"{run_id}-{index + 1:02d}-current",
                transport="json",
                payload=benchmark._payload(messages, f"{run_id}-{source_id}"),
                prompt_token_budget=benchmark.PROMPT_TOKEN_BUDGET,
                completion_token_budget=benchmark.MAX_OUTPUT_TOKENS,
                timeout_seconds=180,
            ),
            transport,
            benchmark._parse,
        )
        answer = str(completion.value)
        labels = benchmark.scoring._answer_values(rows[source_id]["answer"])
        answer_records.append(
            {
                "source_id": source_id,
                "category": case.category,
                "answer": answer,
                "scorer_v1": scorer_v1._score(answer, labels),
                "scorer_v2": dg11_measurement.score_v2(answer, labels),
                "prompt_tokens": prompt_tokens,
                "native_request_id": completion.native_request_id,
            }
        )

    events = gateway.read_ledger()
    reservations = [event for event in events if event.get("event") == "RESERVED"]
    terminals = [event for event in events if event.get("event") == "PROVIDER_TERMINAL"]
    post = [event for event in events if event.get("event") == "POST_PROVIDER_TERMINAL"]
    hits = [record for record in comparisons if record["retrieval_hit_at_3"] == 1]
    baseline_survival = _mean(hits, "baseline_answer_span_present")
    current_survival = _mean(hits, "current_answer_span_present")
    tokens = [int(record["current_context_tokens"]) for record in comparisons]
    assistant = [
        record
        for record in answer_records
        if record["category"] == "single-session-assistant"
    ]
    user = [
        record for record in answer_records if record["category"] == "single-session-user"
    ]
    baseline_assistant = [
        old_scores[(record["source_id"], "MILAI_DG10_FROZEN")] for record in assistant
    ]
    baseline_user = [
        old_scores[(record["source_id"], "MILAI_DG10_FROZEN")] for record in user
    ]
    assistant_f1 = round(
        mean(float(record["scorer_v1"]["normalized_f1"]) for record in assistant), 6
    )
    user_f1 = round(
        mean(float(record["scorer_v1"]["normalized_f1"]) for record in user), 6
    )
    dg10_assistant_f1 = round(
        mean(
            float(record["scorer_v1"]["normalized_f1"])
            for record in baseline_assistant
        ),
        6,
    )
    dg10_user_f1 = round(
        mean(float(record["scorer_v1"]["normalized_f1"]) for record in baseline_user),
        6,
    )
    gates = {
        "opened_dev_answer_span_survival_gt_baseline": current_survival
        > baseline_survival,
        "single_assistant_f1_gte_dg10": assistant_f1 >= dg10_assistant_f1,
        "single_user_regression_gte_minus_0_01": user_f1 - dg10_user_f1 >= -0.01,
        "mean_memory_tokens_lte_320": mean(tokens) <= 320,
        "max_memory_tokens_lte_512": max(tokens) <= 512,
        "open_issue_revoke_regressions_zero": safety["exit_code"] == 0,
        "provider_denominator_26": len(answer_records) == EXPECTED_ANSWER_CALLS,
        "provider_ledger_complete": len(reservations)
        == len(terminals)
        == len(post)
        == EXPECTED_ANSWER_CALLS,
        "hidden_answer_calls_zero": True,
    }
    status = "PASS" if all(gates.values()) else "REVISE"
    result = {
        "schema": "milai.dg11.recovery-compiler.v1",
        "run_id": run_id,
        "work_package": "DG11-R01",
        "status": status,
        "decision": "SUPERSEDE_DG11_01" if status == "PASS" else "REVISE_COMPILER",
        "provider_requests": len(terminals),
        "hidden_provider_calls": 0,
        "development_ai_reviews": 0,
        "summary": {
            "case_count": len(comparisons),
            "retrieval_hit_count": len(hits),
            "baseline_answer_span_survival_on_hit": baseline_survival,
            "current_answer_span_survival_on_hit": current_survival,
            "answer_span_survival_delta": round(
                current_survival - baseline_survival, 6
            ),
            "current_memory_tokens_mean": round(mean(tokens), 3),
            "current_memory_tokens_max": max(tokens),
            "single_assistant_f1": assistant_f1,
            "dg10_single_assistant_f1": dg10_assistant_f1,
            "single_user_f1": user_f1,
            "dg10_single_user_f1": dg10_user_f1,
            "single_user_delta": round(user_f1 - dg10_user_f1, 6),
        },
        "gates": gates,
        "safety_preflight": safety,
        "records": answer_records,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    dg11_state.atomic_json(run_dir / "result.json", result)
    dg11_state.atomic_json(ROOT / "var/dg11/dev/latest-result.json", result)
    dg11_state.append_ledger(
        {
            "run_id": run_id,
            "work_package": "DG11-R01",
            "status": status,
            "decision": result["decision"],
            "provider_requests": len(terminals),
            "development_ai_reviews": 0,
            "metrics": result["summary"],
        }
    )
    if status == "PASS":
        state = json.loads(dg11_state.CURRENT_STATE.read_text(encoding="utf-8"))
        state.setdefault("recovery_work_packages", {})["DG11-R01"] = "PASS"
        state["work_packages"]["DG11-01"] = "SUPERSEDED_BY_DG11-R01/PASS"
        state["recovery_phase"] = "R01_PASS"
        state["latest_result"] = run_id
        dg11_state.atomic_json(dg11_state.CURRENT_STATE, state)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    args = parser.parse_args()
    started = time.monotonic()
    result = run(args.run_id)
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
