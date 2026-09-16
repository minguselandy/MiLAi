from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from milai.adapters.provider_execution import (  # noqa: E402
    JsonCompletionTransport,
    ProviderExecutionGateway,
    ProviderRequest,
)

from scripts import run_dg10_f0 as state  # noqa: E402

MODEL_ID = "Qwen3.6-35B-A3B-FP8"
ENDPOINT = "http://127.0.0.1:7860"
SYSTEM_PROMPT = (
    "Follow the user instruction. Return only a JSON object with one string field named answer. "
    "Do not add markdown, explanations, or other fields."
)
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}
CASES = (
    ("T2-F-01", "Return the exact token DG10-CONTROL-ALPHA.", "DG10-CONTROL-ALPHA"),
    ("T2-F-02", "Return the result of 17 + 25 as digits only.", "42"),
    ("T2-F-03", "Return the lowercase form of MEMORY.", "memory"),
    ("T2-F-04", "Is 9 greater than 4? Return true or false.", "true"),
    ("T2-F-05", "Return the third item in this list: red, green, blue.", "blue"),
)


def _case_payload(case_id: str, prompt: str) -> dict[str, Any]:
    seed = int(hashlib.sha256(case_id.encode()).hexdigest()[:16], 16) & ((1 << 63) - 1)
    return {
        "model": MODEL_ID,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 64,
        "stream": False,
        "seed": seed,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "milai_t2_functional_answer",
                "strict": True,
                "schema": ANSWER_SCHEMA,
            },
        },
        "chat_template_kwargs": {"enable_thinking": False},
        "include_reasoning": False,
        "cache_salt": hashlib.sha256(f"milai-t2:{case_id}".encode()).hexdigest(),
    }


def _parse_answer(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise ValueError("provider payload is not an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("provider choices are invalid")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise ValueError("provider message content is missing")
    answer = json.loads(message["content"])
    if not isinstance(answer, dict) or set(answer) != {"answer"}:
        raise ValueError("provider answer contract is invalid")
    value = answer["answer"]
    if not isinstance(value, str):
        raise ValueError("provider answer is not a string")
    return value


def run_t2(run_id: str, *, endpoint: str = ENDPOINT) -> dict[str, Any]:
    if state._RUN_ID.fullmatch(run_id) is None:
        raise state.F0Error("run_id must be 8-96 lowercase URL-safe characters")
    run_dir = state.RUNS_ROOT / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise state.F0Error(f"run_id already exists: {run_id}") from exc
    os.chmod(run_dir, 0o700)
    dataset_value = [
        {"case_id": case_id, "prompt": prompt, "expected": expected}
        for case_id, prompt, expected in CASES
    ]
    dataset_digest = hashlib.sha256(
        json.dumps(
            dataset_value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    prompt_digest = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
    now = datetime.now(UTC)
    manifest = {
        "schema": "milai.provider.dev-run.v1",
        "run_id": run_id,
        "phase": "functional_f1",
        "provider": "local_vllm",
        "endpoint_identity": endpoint,
        "model_id": MODEL_ID,
        "dataset_manifest_sha256": dataset_digest,
        "prompt_template_sha256": prompt_digest,
        "max_native_requests": len(CASES),
        "max_prompt_tokens": len(CASES) * 512,
        "max_completion_tokens": len(CASES) * 64,
        "deadline": (now + timedelta(minutes=20)).isoformat(),
        "expires_at": (now + timedelta(minutes=30)).isoformat(),
        "synthetic_or_deidentified_only": True,
        "closed_test_access": False,
    }
    manifest_path = run_dir / "manifest.json"
    state._atomic_write(manifest_path, manifest)
    gateway = ProviderExecutionGateway(manifest_path, run_dir / "provider-ledger.jsonl")
    transport = JsonCompletionTransport()
    started = time.monotonic()
    case_results: list[dict[str, Any]] = []
    for case_id, prompt, expected in CASES:
        request = ProviderRequest(
            logical_request_id=f"{run_id}-{case_id.lower()}",
            transport="json",
            payload=_case_payload(case_id, prompt),
            prompt_token_budget=512,
            completion_token_budget=64,
            timeout_seconds=180,
        )
        try:
            completion = gateway.execute(request, transport, _parse_answer)
            passed = completion.value == expected and completion.finish_reason == "stop"
            case_results.append(
                {
                    "case_id": case_id,
                    "status": "PASS" if passed else "FAILED",
                    "expected": expected,
                    "answer": completion.value,
                    "native_request_id": completion.native_request_id,
                    "prompt_tokens": completion.prompt_tokens,
                    "completion_tokens": completion.completion_tokens,
                    "finish_reason": completion.finish_reason,
                    "reason_code": None if passed else "ANSWER_MISMATCH",
                }
            )
        except Exception as exc:
            case_results.append(
                {
                    "case_id": case_id,
                    "status": "FAILED",
                    "expected": expected,
                    "answer": None,
                    "reason_code": type(exc).__name__,
                }
            )
    cases = {item["case_id"]: item["status"] for item in case_results}
    passed_count = sum(value == "PASS" for value in cases.values())
    status_value = "PASS" if passed_count == len(CASES) else "FAILED"
    ledger = gateway.read_ledger()
    native_terminals = [
        event for event in ledger if event.get("event") == "PROVIDER_TERMINAL"
    ]
    if len(native_terminals) != len(CASES):
        status_value = "FAILED"
    result = {
        "schema": "milai.dg10.t2-functional-result.v1",
        "run_id": run_id,
        "status": status_value,
        "cases": cases,
        "case_results": case_results,
        "model_id": MODEL_ID,
        "endpoint_identity": endpoint,
        "provider_requests": len(native_terminals),
        "native_request_ids_unique": len(
            {
                event["native_request_id"]
                for event in native_terminals
                if event.get("native_request_id") is not None
            }
        )
        == len(native_terminals),
        "provider_terminals": len(native_terminals),
        "development_ai_audits": 0,
        "duration_seconds": round(time.monotonic() - started, 6),
        "finished_at": state._now(),
    }
    state._atomic_write(run_dir / "result.json", result)
    experiment = {
        "experiment_id": f"exp-{run_id}",
        "run_id": run_id,
        "timestamp": result["finished_at"],
        "rm_id": "RM-06",
        "rm_ids": ["RM-06"],
        "rm_statuses": {"RM-01": "IN_PROGRESS"},
        "hypothesis": "five deterministic no-memory controls complete through the unique gateway",
        "code_identity": state._tree_identity(
            [ROOT / "runtime/src/milai/adapters/provider_execution.py", Path(__file__).resolve()]
        ),
        "model_identity": MODEL_ID,
        "dataset_identity": dataset_digest,
        "prompt_identity": prompt_digest,
        "budget": {
            "native_requests": len(CASES),
            "prompt_tokens": len(CASES) * 512,
            "completion_tokens": len(CASES) * 64,
        },
        "expected_delta": "T2 functional control 5/5",
        "functional_gate": "NONE",
        "functional_cases_passed": [case for case, value in cases.items() if value == "PASS"],
        "functional_cases_failed": [case for case, value in cases.items() if value != "PASS"],
        "actual_quality_delta": None,
        "actual_token_delta": sum(
            int(item.get("prompt_tokens", 0)) + int(item.get("completion_tokens", 0))
            for item in case_results
        ),
        "actual_latency_delta": None,
        "prepare_context_calls": 0,
        "full_recall_calls": 0,
        "cache_validation_calls": 0,
        "validated_cache_hit_rate": None,
        "relevant_issue_misses": 0,
        "irrelevant_issue_injections": 0,
        "action_revalidation_failures": 0,
        "degraded_or_abstain_count": 0,
        "status": status_value,
    }
    state._record_run(result, experiment)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the five-case DG-10 T2 functional control through ProviderExecutionGateway"
    )
    parser.add_argument(
        "--run-id",
        default=f"t2-functional-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}",
    )
    parser.add_argument("--endpoint", default=ENDPOINT)
    args = parser.parse_args()
    result = run_t2(args.run_id, endpoint=args.endpoint)
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "cases": result["cases"],
                "provider_requests": result["provider_requests"],
            },
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
