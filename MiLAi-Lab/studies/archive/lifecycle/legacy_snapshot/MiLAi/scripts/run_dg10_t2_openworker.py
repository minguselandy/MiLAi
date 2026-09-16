from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from milai.adapters.agent_prefetch import SYSTEM_PROMPT

from evals.agent_integration.f1 import RESPONSE_RULES
from evals.agent_integration.f1_openworker import OpenWorkerHarness, _ledger_events
from scripts import run_dg10_f0 as state
from scripts import run_dg10_f0_native as native

MODEL_ID = "Qwen3.6-35B-A3B-FP8"
ENDPOINT = "http://127.0.0.1:7860"
CASE_IDS = tuple(f"T2-{index:02d}" for index in range(1, 25))
EXPECTED = {"answer": "UNKNOWN", "status": "UNKNOWN", "memory_used": False}


def run_t2_openworker(
    run_id: str,
    package_run_id: str,
    *,
    endpoint: str = ENDPOINT,
) -> dict[str, Any]:
    if state._RUN_ID.fullmatch(run_id) is None:
        raise state.F0Error("run_id must be 8-96 lowercase URL-safe characters")
    client_wheel, mcp_wheel, package_artifacts = native._package_artifacts(package_run_id)
    run_dir = state.RUNS_ROOT / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise state.F0Error(f"run_id already exists: {run_id}") from exc
    os.chmod(run_dir, 0o700)
    dataset = [
        {
            "case_id": case_id,
            "route": "NONE",
            "memory": "NO_MEMORY",
            "expected": EXPECTED,
        }
        for case_id in CASE_IDS
    ]
    dataset_digest = hashlib.sha256(
        json.dumps(dataset, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    prompt_digest = hashlib.sha256((SYSTEM_PROMPT + RESPONSE_RULES).encode()).hexdigest()
    now = datetime.now(UTC)
    provider_manifest = {
        "schema": "milai.provider.dev-run.v1",
        "run_id": run_id,
        "phase": "serving",
        "provider": "local_vllm",
        "endpoint_identity": endpoint,
        "model_id": MODEL_ID,
        "dataset_manifest_sha256": dataset_digest,
        "prompt_template_sha256": prompt_digest,
        "max_native_requests": len(CASE_IDS),
        "max_prompt_tokens": len(CASE_IDS) * 768,
        "max_completion_tokens": len(CASE_IDS) * 96,
        "deadline": (now + timedelta(minutes=40)).isoformat(),
        "expires_at": (now + timedelta(minutes=50)).isoformat(),
        "synthetic_or_deidentified_only": True,
        "closed_test_access": False,
    }
    manifest_path = run_dir / "provider-manifest.json"
    ledger_path = run_dir / "provider-ledger.jsonl"
    adapter_trace = run_dir / "openworker-adapter-trace.jsonl"
    state._atomic_write(manifest_path, provider_manifest)
    state._atomic_write(
        run_dir / "functional-manifest.json",
        {
            "schema": "milai.dg10.functional-run-manifest.v1",
            "run_id": run_id,
            "phase": "t2_openworker_24",
            "cases": list(CASE_IDS),
            "created_at": state._now(),
            "package_run_id": package_run_id,
            "package_artifacts": {
                name: package_artifacts[name] for name in ("client_wheel", "mcp_wheel")
            },
            "data_boundary": "SYNTHETIC_ONLY",
            "container_boundary": "REAL_OPENWORKER_ROUTE_NONE",
            "max_native_requests": len(CASE_IDS),
            "development_ai_audits": 0,
        },
    )
    started = time.monotonic()
    command_trace: list[dict[str, Any]] = []
    harness: OpenWorkerHarness | None = None
    case_results: list[dict[str, Any]] = []
    cleanup: dict[str, Any] = {"status": "NOT_STARTED"}
    security: dict[str, Any] = {"secret_scan": "NOT_STARTED"}
    setup_error: str | None = None
    try:
        with tempfile.TemporaryDirectory(prefix=f"milai-{run_id}-") as temporary:
            install = state._probe_install(
                kind="wheel",
                client_artifact=client_wheel,
                mcp_artifact=mcp_wheel,
                workspace=Path(temporary).resolve() / "installed-product",
                trace=command_trace,
            )
            harness = OpenWorkerHarness(
                Path(temporary).resolve() / "openworker",
                run_id,
                Path(install["entrypoint"]),
                manifest_path,
                ledger_path,
                adapter_trace,
                memory_mode="none",
            )
            harness.workspace.mkdir(mode=0o700)
            harness.start_model_plane()
            harness._start_memory_plane(
                "http://127.0.0.1:9",
                "synthetic-t2-reader-" + secrets.token_urlsafe(40),
            )
            for case_id in CASE_IDS:
                try:
                    agent = harness.no_memory_control(case_id)
                    passed = (
                        agent.answer == EXPECTED
                        and agent.tool_names == ()
                        and agent.provider_calls == 1
                    )
                    case_results.append(
                        {
                            "case_id": case_id,
                            "status": "PASS" if passed else "FAILED",
                            **agent.public(),
                            "reason_code": None if passed else "T2_TERMINAL_MISMATCH",
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - preserve every failed denominator
                    case_results.append(
                        {
                            "case_id": case_id,
                            "status": "FAILED",
                            "reason_code": type(exc).__name__,
                        }
                    )
            security = harness.security()
    except Exception as exc:  # noqa: BLE001 - preserve setup failures as a run result
        setup_error = f"{type(exc).__name__}: {exc}"
    finally:
        if harness is not None:
            cleanup = harness.close()

    by_id = {record["case_id"]: record for record in case_results}
    for case_id in CASE_IDS:
        by_id.setdefault(
            case_id,
            {
                "case_id": case_id,
                "status": "FAILED",
                "reason_code": "SETUP_FAILED",
            },
        )
    case_results = [by_id[case_id] for case_id in CASE_IDS]
    cases = {record["case_id"]: record["status"] for record in case_results}
    events = _ledger_events(ledger_path)
    reservations = [event for event in events if event.get("event") == "RESERVED"]
    terminals = [event for event in events if event.get("event") == "PROVIDER_TERMINAL"]
    post = [event for event in events if event.get("event") == "POST_PROVIDER_TERMINAL"]
    adapter_events = (
        [json.loads(line) for line in adapter_trace.read_text().splitlines()]
        if adapter_trace.is_file()
        else []
    )
    provider_answers = [
        event for event in adapter_events if event.get("event") == "PROVIDER_ANSWER"
    ]
    all_pass = all(value == "PASS" for value in cases.values())
    trace_pass = (
        len(reservations) == len(CASE_IDS)
        and len(terminals) == len(CASE_IDS)
        and len(post) == len(CASE_IDS)
        and len({event["native_request_id"] for event in terminals}) == len(CASE_IDS)
        and len(provider_answers) == len(CASE_IDS)
        and all(event.get("memory_status") == "NO_MEMORY" for event in provider_answers)
        and all(event.get("context_in_prompt") is True for event in provider_answers)
    )
    status = (
        "PASS"
        if (
            all_pass
            and trace_pass
            and cleanup.get("status") == "PASS"
            and security.get("secret_scan") == "PASS"
        )
        else "FAILED"
    )
    result = {
        "schema": "milai.dg10.t2-openworker-result.v1",
        "run_id": run_id,
        "package_run_id": package_run_id,
        "status": status,
        "cases": cases,
        "case_results": case_results,
        "model_id": MODEL_ID,
        "endpoint_identity": endpoint,
        "provider_requests": len(terminals),
        "provider_reservations": len(reservations),
        "post_provider_terminals": len(post),
        "native_request_ids_unique": len(
            {event["native_request_id"] for event in terminals}
        )
        == len(terminals),
        "hidden_model_calls": 0 if len(terminals) == len(reservations) else None,
        "route": "OPENWORKER_GATEWAY_NONE",
        "security": security,
        "cleanup": cleanup,
        "development_ai_audits": 0,
        "duration_seconds": round(time.monotonic() - started, 6),
        "error": setup_error,
        "finished_at": state._now(),
    }
    state._atomic_write(run_dir / "trace.json", {"commands": command_trace})
    state._atomic_write(run_dir / "result.json", result)
    experiment = {
        "experiment_id": f"exp-{run_id}",
        "run_id": run_id,
        "timestamp": result["finished_at"],
        "rm_id": "RM-06",
        "rm_ids": ["RM-01", "RM-06"],
        "hypothesis": (
            "24 no-memory route-NONE cases terminate through real OpenWorker, Gateway, the "
            "product ProviderExecutionGateway and local vLLM without post-provider loss"
        ),
        "code_identity": state._tree_identity(
            [
                ROOT / "integrations/openworker-mcp/src/milai_openworker_mcp/adapter.py",
                ROOT / "evals/agent_integration/f1_openworker.py",
                ROOT / "runtime/src/milai/adapters/provider_execution.py",
                Path(__file__).resolve(),
            ]
        ),
        "model_identity": MODEL_ID,
        "dataset_identity": dataset_digest,
        "prompt_identity": prompt_digest,
        "budget": {
            "native_requests": len(CASE_IDS),
            "prompt_tokens": len(CASE_IDS) * 768,
            "completion_tokens": len(CASE_IDS) * 96,
        },
        "expected_delta": "T2 real OpenWorker route-NONE terminal success 24/24",
        "functional_gate": "T2_24",
        "functional_cases_passed": [case for case, value in cases.items() if value == "PASS"],
        "functional_cases_failed": [case for case, value in cases.items() if value != "PASS"],
        "actual_quality_delta": None,
        "actual_token_delta": sum(
            int(record.get("prompt_tokens", 0)) + int(record.get("completion_tokens", 0))
            for record in case_results
        ),
        "actual_latency_delta": None,
        "prepare_context_calls": 0,
        "full_recall_calls": 0,
        "cache_validation_calls": 0,
        "validated_cache_hit_rate": None,
        "relevant_issue_misses": 0,
        "irrelevant_issue_injections": 0,
        "action_revalidation_failures": 0,
        "degraded_or_abstain_count": len(CASE_IDS),
        "status": status,
    }
    state._record_run(result, experiment)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the 24-case real OpenWorker T2 control")
    parser.add_argument(
        "--run-id",
        default=(
            "t2-openworker-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        ),
    )
    parser.add_argument("--package-run-id", required=True)
    parser.add_argument("--endpoint", default=ENDPOINT)
    args = parser.parse_args()
    result = run_t2_openworker(args.run_id, args.package_run_id, endpoint=args.endpoint)
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "passed": sum(value == "PASS" for value in result["cases"].values()),
                "provider_requests": result["provider_requests"],
            },
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
