from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from milai.adapters.agent_prefetch import SYSTEM_PROMPT

from evals.agent_integration import f1
from evals.serving import minimal_baseline
from scripts import run_dg10_f0 as state
from scripts import run_dg10_f0_native as native

ENDPOINT = "http://127.0.0.1:7860"
MODEL_ID = "Qwen3.6-35B-A3B-FP8"
TOKENIZER_JSON = Path("/cra/qwen36-35B/tokenizer.json")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _t2_24_passed() -> bool:
    for path in sorted(
        state.RUNS_ROOT.glob("t2-openworker-*/result.json"), reverse=True
    ):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cases = value.get("cases")
        if (
            value.get("schema") == "milai.dg10.t2-openworker-result.v1"
            and value.get("status") == "PASS"
            and isinstance(cases, dict)
            and len(cases) == 24
            and all(status == "PASS" for status in cases.values())
        ):
            return True
    return False


def _provider_manifest(
    *,
    tier_run_id: str,
    endpoint: str,
    dataset_digest: str,
    prompt_digest: str,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    repetitions = minimal_baseline.REPETITIONS
    return {
        "schema": "milai.provider.dev-run.v1",
        "run_id": tier_run_id,
        "phase": "serving",
        "provider": "local_vllm",
        "endpoint_identity": endpoint,
        "model_id": MODEL_ID,
        "dataset_manifest_sha256": dataset_digest,
        "prompt_template_sha256": prompt_digest,
        "max_native_requests": repetitions,
        "max_prompt_tokens": repetitions * minimal_baseline.PROMPT_TOKEN_BUDGET,
        "max_completion_tokens": repetitions * minimal_baseline.COMPLETION_TOKEN_BUDGET,
        "deadline": (now + timedelta(minutes=90)).isoformat(),
        "expires_at": (now + timedelta(minutes=100)).isoformat(),
        "synthetic_or_deidentified_only": True,
        "closed_test_access": False,
    }


def _tier_cases(report: Mapping[str, Any], status: str) -> dict[str, str]:
    aggregates = report.get("aggregates")
    if status != "PASS" or not isinstance(aggregates, dict):
        return {tier: "FAILED" for tier in minimal_baseline.TIERS}
    return {
        tier: (
            "PASS"
            if isinstance(aggregates.get(tier), dict)
            and aggregates[tier].get("request_count") == minimal_baseline.REPETITIONS
            and aggregates[tier].get("failure_count") == 0
            else "FAILED"
        )
        for tier in minimal_baseline.TIERS
    }


def _experiment(
    *,
    run_id: str,
    result: Mapping[str, Any],
    report: Mapping[str, Any],
    dataset_digest: str,
    prompt_digest: str,
) -> dict[str, Any]:
    status = str(result["status"])
    comparison = report.get("comparison") or {}
    optimized = comparison.get("baseline_run_id") is not None
    return {
        "experiment_id": f"exp-{run_id}",
        "run_id": run_id,
        "timestamp": result["finished_at"],
        "rm_id": "RM-12",
        "rm_ids": ["RM-06", "RM-07", "RM-12", "RM-13"],
        "rm_statuses": {"RM-12": "IN_PROGRESS", "RM-13": "IN_PROGRESS"},
        "hypothesis": (
            "host-owned deterministic prefetch over one task-long UDS MCP session removes "
            "the OpenCode synthetic tool round-trip and brings warm memory-control p95 "
            "within 250 ms without changing answer calls or task inputs"
            if optimized
            else (
                "a same-task T0/T1/T2/T3a Latin-square baseline will isolate the largest "
                "serving overhead while preserving one native answer call per tier request"
            )
        ),
        "code_identity": state._tree_identity(
            [
                ROOT / "evals/serving/minimal_baseline.py",
                ROOT
                / "integrations/openworker-mcp/src/milai_openworker_mcp/adapter.py",
                ROOT / "evals/agent_integration/f1_openworker.py",
                ROOT / "runtime/src/milai/adapters/mcp_unix.py",
                Path(__file__).resolve(),
            ]
        ),
        "model_identity": MODEL_ID,
        "dataset_identity": dataset_digest,
        "prompt_identity": prompt_digest,
        "budget": {
            "native_requests": len(minimal_baseline.TIERS)
            * minimal_baseline.REPETITIONS,
            "prompt_tokens": len(minimal_baseline.TIERS)
            * minimal_baseline.REPETITIONS
            * minimal_baseline.PROMPT_TOKEN_BUDGET,
            "completion_tokens": len(minimal_baseline.TIERS)
            * minimal_baseline.REPETITIONS
            * minimal_baseline.COMPLETION_TOKEN_BUDGET,
        },
        "expected_delta": (
            "warm memory-control p95 <=250 ms with 124/124 terminal success"
            if optimized
            else "identify the largest measured T3a serving component"
        ),
        "functional_gate": "MINIMAL_SERVING",
        "functional_cases_passed": list(minimal_baseline.TIERS)
        if status == "PASS"
        else [],
        "functional_cases_failed": []
        if status == "PASS"
        else list(minimal_baseline.TIERS),
        "actual_quality_delta": None,
        "actual_token_delta": None,
        "actual_latency_delta": (
            comparison.get("t3a_warm_e2e_mean_delta_ms")
            if optimized
            else (report.get("derived_warm_overhead_ms") or {}).get(
                "effective_memory_e2e_mean"
            )
        ),
        "prepare_context_calls": minimal_baseline.REPETITIONS,
        "full_recall_calls": minimal_baseline.REPETITIONS,
        "cache_validation_calls": 0,
        "validated_cache_hit_rate": None,
        "relevant_issue_misses": 0,
        "irrelevant_issue_injections": 0,
        "action_revalidation_failures": 0,
        "degraded_or_abstain_count": 0,
        "decision": comparison.get("decision", "BASELINE_ONLY"),
        "next_action": (
            "rerun affected OpenWorker functional path, then continue the next measured gap"
            if comparison.get("decision") == "KEEP_EFFICIENCY"
            else "inspect the retained failed denominator before another mechanism change"
        ),
        "status": status,
    }


def _baseline_report(
    baseline_run_id: str,
    *,
    dataset_digest: str,
    prompt_digest: str,
) -> dict[str, Any]:
    if state._RUN_ID.fullmatch(baseline_run_id) is None:
        raise state.F0Error("baseline_run_id is invalid")
    run_dir = state.RUNS_ROOT / baseline_run_id
    try:
        manifest = json.loads((run_dir / "serving-manifest.json").read_text())
        report = json.loads((run_dir / "report.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise state.F0Error("serving comparison baseline is incomplete") from exc
    if (
        manifest.get("dataset_contract_sha256") != dataset_digest
        or manifest.get("prompt_contract_sha256") != prompt_digest
        or report.get("status") != "PASS_BASELINE_RECORDED"
    ):
        raise state.F0Error("serving comparison baseline contract drifted")
    return report


def _comparison(
    baseline_run_id: str,
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_aggregates = baseline.get("aggregates") or {}
    current_aggregates = current.get("aggregates") or {}
    before_t3 = (baseline_aggregates.get("T3a") or {}).get("warm_e2e_ms") or {}
    after_t3 = (current_aggregates.get("T3a") or {}).get("warm_e2e_ms") or {}
    before_memory = (baseline_aggregates.get("T3a") or {}).get(
        "warm_memory_control_ms"
    ) or {}
    after_memory = (current_aggregates.get("T3a") or {}).get(
        "warm_memory_control_ms"
    ) or {}
    values = (
        before_t3.get("mean"),
        after_t3.get("mean"),
        before_t3.get("p95"),
        after_t3.get("p95"),
        before_memory.get("p95"),
        after_memory.get("p95"),
    )
    if any(value is None for value in values):
        raise state.F0Error("serving comparison metrics are incomplete")
    complete = all(
        (current_aggregates.get(tier) or {}).get("failure_count") == 0
        and (current_aggregates.get(tier) or {}).get("request_count")
        == minimal_baseline.REPETITIONS
        for tier in minimal_baseline.TIERS
    )
    memory_target_pass = float(after_memory["p95"]) <= 250
    e2e_improved = float(after_t3["mean"]) < float(before_t3["mean"])
    if complete and memory_target_pass and e2e_improved:
        decision = "KEEP_EFFICIENCY"
    elif not complete or float(after_t3["mean"]) > float(before_t3["mean"]):
        decision = "REVERT"
    else:
        decision = "REDESIGN"
    return {
        "baseline_run_id": baseline_run_id,
        "same_dataset_contract": True,
        "same_prompt_contract": True,
        "terminal_failures": sum(
            int((current_aggregates.get(tier) or {}).get("failure_count", 0))
            for tier in minimal_baseline.TIERS
        ),
        "t3a_warm_e2e_mean_before_ms": before_t3["mean"],
        "t3a_warm_e2e_mean_after_ms": after_t3["mean"],
        "t3a_warm_e2e_mean_delta_ms": round(
            float(after_t3["mean"]) - float(before_t3["mean"]), 3
        ),
        "t3a_warm_e2e_p95_before_ms": before_t3["p95"],
        "t3a_warm_e2e_p95_after_ms": after_t3["p95"],
        "t3a_warm_e2e_p95_delta_ms": round(
            float(after_t3["p95"]) - float(before_t3["p95"]), 3
        ),
        "memory_control_p95_before_ms": before_memory["p95"],
        "memory_control_p95_after_ms": after_memory["p95"],
        "memory_control_p95_delta_ms": round(
            float(after_memory["p95"]) - float(before_memory["p95"]), 3
        ),
        "memory_control_target_ms": 250,
        "decision": decision,
    }


def run_serving(
    run_id: str,
    package_run_id: str,
    *,
    endpoint: str = ENDPOINT,
    baseline_run_id: str | None = None,
) -> dict[str, Any]:
    if state._RUN_ID.fullmatch(run_id) is None:
        raise state.F0Error("run_id must be 8-96 lowercase URL-safe characters")
    current = json.loads(state.CURRENT_STATE.read_text(encoding="utf-8"))
    gates = current.get("functional_gates") or {}
    if gates.get("F0") != "PASS" or gates.get("F1") != "PASS" or not _t2_24_passed():
        raise state.F0Error("minimal serving requires F0, F1, and T2 24/24 PASS")
    package_paths, package_artifacts = native._package_artifact_map(package_run_id)
    required_packages = {
        "client_wheel",
        "mcp_wheel",
        "runtime_wheel",
        "openworker_wheel",
    }
    if not required_packages.issubset(package_paths):
        raise state.F0Error("package run predates the OpenWorker composite product")
    run_dir = state.RUNS_ROOT / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise state.F0Error(f"run_id already exists: {run_id}") from exc
    os.chmod(run_dir, 0o700)

    dataset_contract = {
        "task": "synthetic governed runtime version lookup",
        "tiers": list(minimal_baseline.TIERS),
        "repetitions_per_tier": minimal_baseline.REPETITIONS,
        "cold_samples_per_tier": 1,
        "warm_samples_per_tier": minimal_baseline.WARM_REPETITIONS,
        "latin_square": True,
    }
    prompt_contract = {
        "system_prompt": SYSTEM_PROMPT,
        "response_rules": f1.RESPONSE_RULES,
        "user_template": (
            "Use the available milai_recall capability when memory is enabled. "
            "What runtime Python version is recorded for synthetic project {marker}? "
            "Return only the required JSON answer and preserve uncertainty."
        ),
        "generation": {
            "model": MODEL_ID,
            "temperature": 0,
            "max_tokens": minimal_baseline.COMPLETION_TOKEN_BUDGET,
            "stream": False,
            "answer_schema": f1.ANSWER_SCHEMA,
            "enable_thinking": False,
        },
    }
    dataset_digest = _digest(dataset_contract)
    prompt_digest = _digest(prompt_contract)
    baseline = (
        _baseline_report(
            baseline_run_id,
            dataset_digest=dataset_digest,
            prompt_digest=prompt_digest,
        )
        if baseline_run_id is not None
        else None
    )
    manifests: dict[str, Path] = {}
    ledgers: dict[str, Path] = {}
    traces: dict[str, Path] = {}
    for tier in minimal_baseline.TIERS:
        slug = tier.casefold()
        tier_run_id = f"{run_id}-{slug}"
        tier_dir = run_dir / slug
        tier_dir.mkdir(mode=0o700)
        manifest = tier_dir / "provider-manifest.json"
        state._atomic_write(
            manifest,
            _provider_manifest(
                tier_run_id=tier_run_id,
                endpoint=endpoint,
                dataset_digest=dataset_digest,
                prompt_digest=prompt_digest,
            ),
        )
        manifests[tier] = manifest
        if tier != "T0":
            ledgers[tier] = tier_dir / "provider-ledger.jsonl"
        if tier in {"T2", "T3a"}:
            traces[tier] = tier_dir / "openworker-adapter-trace.jsonl"
    state._atomic_write(
        run_dir / "serving-manifest.json",
        {
            "schema": "milai.dg10.minimal-serving-manifest.v1",
            "run_id": run_id,
            "package_run_id": package_run_id,
            "package_artifacts": {
                name: package_artifacts[name] for name in sorted(required_packages)
            },
            "dataset_contract": dataset_contract,
            "dataset_contract_sha256": dataset_digest,
            "prompt_contract": prompt_contract,
            "prompt_contract_sha256": prompt_digest,
            "expected_native_requests": len(minimal_baseline.TIERS)
            * minimal_baseline.REPETITIONS,
            "development_ai_audits": 0,
            "comparison_baseline_run_id": baseline_run_id,
        },
    )

    trace: list[dict[str, Any]] = []
    report: dict[str, Any] = {}
    error: str | None = None
    status = "FAILED"
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix=f"milai-{run_id}-") as temporary:
            install = state._probe_install(
                kind="wheel",
                client_artifact=package_paths["client_wheel"],
                mcp_artifact=package_paths["mcp_wheel"],
                runtime_artifact=package_paths["runtime_wheel"],
                runtime_extras=("embedding",),
                openworker_artifact=package_paths["openworker_wheel"],
                workspace=Path(temporary).resolve() / "installed-product",
                trace=trace,
            )
            previous = os.environ.get("DG10_MCP_HOST_PYTHON")
            os.environ["DG10_MCP_HOST_PYTHON"] = install["python"]
            try:
                report = minimal_baseline.run(
                    env_file=ROOT / "runtime/.env",
                    manifests=manifests,
                    ledgers=ledgers,
                    traces=traces,
                    mcp_executable=Path(install["entrypoint"]),
                    tokenizer_json=TOKENIZER_JSON,
                    adapter_python=Path(install["python"]),
                )
            finally:
                if previous is None:
                    os.environ.pop("DG10_MCP_HOST_PYTHON", None)
                else:
                    os.environ["DG10_MCP_HOST_PYTHON"] = previous
        report["experiment_kind"] = (
            "OPTIMIZATION" if baseline is not None else "BASELINE"
        )
        if baseline is not None and baseline_run_id is not None:
            report["comparison"] = _comparison(baseline_run_id, baseline, report)
        state._atomic_write(run_dir / "report.json", report)
        if report.get("status") != "PASS_BASELINE_RECORDED":
            raise state.F0Error("minimal serving denominator is incomplete")
        status = "PASS"
    except Exception as exc:  # noqa: BLE001 - preserve failed serving denominator
        error = f"{type(exc).__name__}: {exc}"
        if report:
            state._atomic_write(run_dir / "report.json", report)

    result = {
        "schema": "milai.dg10.minimal-serving-result.v1",
        "run_id": run_id,
        "status": status,
        "cases": _tier_cases(report, status),
        "provider_requests": (report.get("provider_trace") or {}).get(
            "observed_native_requests", 0
        ),
        "aggregates": report.get("aggregates"),
        "derived_warm_overhead_ms": report.get("derived_warm_overhead_ms"),
        "memory_control_target": report.get("memory_control_target"),
        "comparison": report.get("comparison"),
        "development_ai_audits": 0,
        "duration_seconds": round(time.monotonic() - started, 6),
        "error": error,
        "finished_at": state._now(),
    }
    state._atomic_write(run_dir / "trace.json", {"commands": trace})
    state._atomic_write(run_dir / "result.json", result)
    experiment = _experiment(
        run_id=run_id,
        result=result,
        report=report,
        dataset_digest=dataset_digest,
        prompt_digest=prompt_digest,
    )
    state._record_run(result, experiment)
    return result


def finalize_existing(run_id: str) -> dict[str, Any]:
    run_dir = state.RUNS_ROOT / run_id
    manifest_path = run_dir / "serving-manifest.json"
    report_path = run_dir / "report.json"
    result_path = run_dir / "result.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise state.F0Error("existing serving artifacts are incomplete") from exc
    provider = report.get("provider_trace") or {}
    cleanup = report.get("cleanup") or {}
    expected = len(minimal_baseline.TIERS) * minimal_baseline.REPETITIONS
    if (
        report.get("status") != "PASS_BASELINE_RECORDED"
        or result.get("status") != "PASS"
        or provider.get("observed_native_requests") != expected
        or provider.get("unique_native_request_ids") != expected
        or set(cleanup) != {"T2", "T3a", "database"}
        or any(value.get("status") != "PASS" for value in cleanup.values())
    ):
        raise state.F0Error("existing serving evidence does not prove a complete run")
    result["cases"] = _tier_cases(report, "PASS")
    state._atomic_write(result_path, result)
    experiment = _experiment(
        run_id=run_id,
        result=result,
        report=report,
        dataset_digest=str(manifest["dataset_contract_sha256"]),
        prompt_digest=str(manifest["prompt_contract_sha256"]),
    )
    state._record_run(result, experiment)
    return result


def reclassify_existing(run_id: str, baseline_run_id: str) -> dict[str, Any]:
    run_dir = state.RUNS_ROOT / run_id
    manifest_path = run_dir / "serving-manifest.json"
    report_path = run_dir / "report.json"
    result_path = run_dir / "result.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_report = json.loads(report_path.read_text(encoding="utf-8"))
        source_result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise state.F0Error("existing serving artifacts are incomplete") from exc
    records = source_report.get("records")
    provider = source_report.get("provider_trace") or {}
    cleanup = source_report.get("cleanup") or {}
    expected = len(minimal_baseline.TIERS) * minimal_baseline.REPETITIONS
    native_ids = (
        [record.get("native_request_id") for record in records]
        if isinstance(records, list)
        else []
    )
    if (
        manifest.get("expected_native_requests") != expected
        or not isinstance(records, list)
        or len(records) != expected
        or provider.get("observed_native_requests") != expected
        or provider.get("unique_native_request_ids") != expected
        or len(native_ids) != len(set(native_ids))
        or any(not isinstance(value, str) or not value for value in native_ids)
        or set(cleanup) != {"T2", "T3a", "database"}
        or any(value.get("status") != "PASS" for value in cleanup.values())
    ):
        raise state.F0Error("existing serving execution evidence is incomplete")
    classified = [minimal_baseline.reclassify_record(record) for record in records]
    aggregates = minimal_baseline.aggregate(classified)
    complete = all(
        aggregates[tier]["request_count"] == minimal_baseline.REPETITIONS
        and aggregates[tier]["failure_count"] == 0
        for tier in minimal_baseline.TIERS
    )
    t0 = aggregates["T0"]["warm_e2e_ms"]
    t1 = aggregates["T1"]["warm_e2e_ms"]
    t2 = aggregates["T2"]["warm_e2e_ms"]
    t3a = aggregates["T3a"]["warm_e2e_ms"]
    memory_p95 = aggregates["T3a"]["warm_memory_control_ms"]["p95"]
    derived = {
        "gateway_mean": round(float(t1["mean"]) - float(t0["mean"]), 3),
        "agent_integration_mean": round(float(t2["mean"]) - float(t1["mean"]), 3),
        "effective_memory_e2e_mean": round(
            float(t3a["mean"]) - float(t1["mean"]), 3
        ),
    }
    reclassified_report = {
        **source_report,
        "schema": "milai.dg10.minimal-serving-reclassification.v1",
        "status": "PASS_RECLASSIFIED" if complete else "FAILED",
        "source_run_id": run_id,
        "source_report_sha256": state._sha256(report_path),
        "source_result_sha256": state._sha256(result_path),
        "source_status": source_result.get("status"),
        "classification_change": (
            "T3a host composite context replaces the obsolete host prefetch label"
        ),
        "new_provider_requests": 0,
        "records": classified,
        "aggregates": aggregates,
        "derived_warm_overhead_ms": derived,
        "memory_control_target": {
            "warm_p95_ms": 250,
            "observed_p95_ms": memory_p95,
            "status": "PASS" if memory_p95 is not None and memory_p95 <= 250 else "FAILED",
        },
        "provider_trace": {**provider, "hidden_model_calls": 0 if complete else None},
    }
    baseline = _baseline_report(
        baseline_run_id,
        dataset_digest=str(manifest["dataset_contract_sha256"]),
        prompt_digest=str(manifest["prompt_contract_sha256"]),
    )
    reclassified_report["comparison"] = _comparison(
        baseline_run_id,
        baseline,
        reclassified_report,
    )
    output_path = run_dir / "reclassification.json"
    if output_path.exists():
        raise state.F0Error("serving reclassification already exists")
    state._atomic_write(output_path, reclassified_report)
    return {
        "run_id": run_id,
        "status": reclassified_report["status"],
        "provider_requests": expected,
        "new_provider_requests": 0,
        "derived_warm_overhead_ms": derived,
        "memory_control_target": reclassified_report["memory_control_target"],
        "comparison": reclassified_report["comparison"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the DG-10 minimal T0/T1/T2/T3a baseline"
    )
    parser.add_argument(
        "--run-id",
        default=(
            "serving-minimal-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        ),
    )
    parser.add_argument("--package-run-id", required=True)
    parser.add_argument("--endpoint", default=ENDPOINT)
    parser.add_argument("--baseline-run-id")
    parser.add_argument("--finalize-existing", action="store_true")
    parser.add_argument("--reclassify-existing", action="store_true")
    args = parser.parse_args()
    if args.finalize_existing and args.reclassify_existing:
        parser.error("choose only one existing-run operation")
    if args.reclassify_existing:
        if args.baseline_run_id is None:
            parser.error("--reclassify-existing requires --baseline-run-id")
        result = reclassify_existing(args.run_id, args.baseline_run_id)
    elif args.finalize_existing:
        result = finalize_existing(args.run_id)
    else:
        result = run_serving(
            args.run_id,
            args.package_run_id,
            endpoint=args.endpoint,
            baseline_run_id=args.baseline_run_id,
        )
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "provider_requests": result["provider_requests"],
                "derived_warm_overhead_ms": result["derived_warm_overhead_ms"],
                "memory_control_target": result["memory_control_target"],
                "comparison": result.get("comparison"),
            },
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
