from __future__ import annotations

import argparse
import hashlib
import json
import os
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

from evals.benchmark import lme_product_smoke as benchmark
from scripts import run_dg10_f0 as state
from scripts import run_dg10_f0_native as native

ENDPOINT = "http://127.0.0.1:7860"
DEFAULT_DATASET = ROOT.parent / "benchmarks/LongMemEval/data/longmemeval_s_cleaned.json"
FREEZE_ROOT = ROOT / "var/dg10/freeze"
CONFIRMATION_CONSUMPTION = FREEZE_ROOT / "confirmation-consumption-003.json"


def confirmation_code_identity() -> str:
    return state._tree_identity(
        [
            ROOT / "evals/benchmark/lme_product_smoke.py",
            ROOT / "evals/benchmark/lme_product_worker.py",
            ROOT / "scripts/run_dg10_lme_product_smoke.py",
            ROOT / "scripts/run_dg10_lme_product_confirmation.py",
            ROOT / "scripts/run_dg10_freeze_preflight.py",
            ROOT / "scripts/run_dg10_finalize_candidate.py",
            ROOT / "runtime/src/milai/adapters/provider_execution.py",
            ROOT / "evals/serving/minimal_baseline.py",
            ROOT / "scripts/run_dg10_minimal_serving.py",
            ROOT / "MiLAi_DG-10实验结果整改与复验_GOALS.md",
        ]
    )


def _consume_confirmation(
    *,
    freeze_manifest: Path,
    run_id: str,
    package_run_id: str,
    dataset_digest: str,
    prompt_digest: str,
    source_ids_digest: str,
) -> None:
    resolved = freeze_manifest.resolve()
    if resolved.parent != FREEZE_ROOT.resolve() or not resolved.is_file():
        raise state.F0Error("confirmation freeze manifest path is invalid")
    try:
        frozen = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise state.F0Error("confirmation freeze manifest is unreadable") from exc
    if (
        frozen.get("schema") != "milai.dg10.freeze-manifest.v1"
        or frozen.get("status") != "FROZEN"
        or frozen.get("package_run_id") != package_run_id
        or frozen.get("model_id") != benchmark.MODEL_ID
        or frozen.get("dataset_sha256") != dataset_digest
        or frozen.get("prompt_contract_sha256") != prompt_digest
        or frozen.get("confirmation_source_ids_sha256") != source_ids_digest
        or frozen.get("confirmation_case_ids_sha256")
        != benchmark.CONFIRMATION_CASE_IDS_SHA256
        or frozen.get("confirmation_case_count")
        != len(benchmark.CONFIRMATION_SOURCE_IDS)
        or frozen.get("confirmation_code_identity") != confirmation_code_identity()
        or frozen.get("development_ai_audits") != 0
    ):
        raise state.F0Error("confirmation freeze manifest drifted")
    configured_consumption = frozen.get("confirmation_consumption_path")
    if (
        not isinstance(configured_consumption, str)
        or (ROOT / configured_consumption).resolve() != CONFIRMATION_CONSUMPTION.resolve()
    ):
        raise state.F0Error("confirmation consumption path drifted")
    CONFIRMATION_CONSUMPTION.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(CONFIRMATION_CONSUMPTION, flags, 0o600)
    except FileExistsError as exc:
        raise state.F0Error("confirmation capability was already consumed") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "schema": "milai.dg10.confirmation-consumption.v1",
                "run_id": run_id,
                "package_run_id": package_run_id,
                "freeze_manifest_sha256": state._sha256(resolved),
                "consumed_at": state._now(),
                "new_attempts_allowed": False,
            },
            handle,
            ensure_ascii=False,
            sort_keys=True,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _provider_ledger_summary(
    manifest_path: Path,
    ledger_path: Path,
) -> dict[str, Any]:
    try:
        events = benchmark.ProviderExecutionGateway(
            manifest_path,
            ledger_path,
        ).read_ledger()
    except Exception as exc:  # noqa: BLE001 - preserve a failed run without trusting it
        return {
            "status": "INVALID",
            "error": f"{type(exc).__name__}: {exc}",
            "reservations": 0,
            "provider_terminals": 0,
            "post_provider_terminals": 0,
            "native_requests_started": 0,
            "native_request_ids_observed": 0,
        }
    terminals = [event for event in events if event.get("event") == "PROVIDER_TERMINAL"]
    return {
        "status": "VALID",
        "error": None,
        "reservations": sum(event.get("event") == "RESERVED" for event in events),
        "provider_terminals": len(terminals),
        "post_provider_terminals": sum(
            event.get("event") == "POST_PROVIDER_TERMINAL" for event in events
        ),
        "native_requests_started": sum(
            event.get("request_started") is True for event in terminals
        ),
        "native_request_ids_observed": sum(
            isinstance(event.get("native_request_id"), str) for event in terminals
        ),
    }


def run_benchmark(
    run_id: str,
    package_run_id: str,
    *,
    phase: str,
    source_ids: tuple[str, ...],
    dataset: Path = DEFAULT_DATASET,
    endpoint: str = ENDPOINT,
    freeze_manifest: Path | None = None,
) -> dict[str, Any]:
    if phase not in {"SMOKE", "DEV", "CONFIRMATION"}:
        raise state.F0Error("LongMemEval phase must be SMOKE, DEV, or CONFIRMATION")
    if state._RUN_ID.fullmatch(run_id) is None:
        raise state.F0Error("run_id must be 8-96 lowercase URL-safe characters")
    current = json.loads(state.CURRENT_STATE.read_text(encoding="utf-8"))
    gates = current.get("functional_gates") or {}
    if gates.get("F0") != "PASS" or gates.get("F1") != "PASS":
        raise state.F0Error("LongMemEval smoke requires F0 and F1 PASS")
    package_paths, package_artifacts = native._package_artifact_map(package_run_id)
    required_packages = {
        "client_wheel",
        "mcp_wheel",
        "runtime_wheel",
        "openworker_wheel",
    }
    if not required_packages.issubset(package_paths):
        raise state.F0Error("package run does not contain the complete product")
    run_dir = state.RUNS_ROOT / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise state.F0Error(f"run_id already exists: {run_id}") from exc
    os.chmod(run_dir, 0o700)
    dataset_digest = state._sha256(dataset)
    source_ids_digest = hashlib.sha256(benchmark._canonical(source_ids)).hexdigest()
    dataset_contract_digest = hashlib.sha256(
        benchmark._canonical(
            {
                "dataset_sha256": dataset_digest,
                "phase": phase,
                "source_case_ids": list(source_ids),
            }
        )
    ).hexdigest()
    prompt_digest = benchmark.prompt_contract_sha256()
    if phase == "CONFIRMATION":
        if freeze_manifest is None:
            raise state.F0Error("LongMemEval confirmation requires a freeze manifest")
        _consume_confirmation(
            freeze_manifest=freeze_manifest,
            run_id=run_id,
            package_run_id=package_run_id,
            dataset_digest=dataset_digest,
            prompt_digest=prompt_digest,
            source_ids_digest=source_ids_digest,
        )
    elif freeze_manifest is not None:
        raise state.F0Error("freeze manifests are only valid for confirmation")
    now = datetime.now(UTC)
    request_count = len(source_ids) * len(benchmark.ARMS)
    provider_manifest = {
        "schema": (
            "milai.provider.closed-test-run.v1"
            if phase == "CONFIRMATION"
            else "milai.provider.dev-run.v1"
        ),
        "run_id": run_id,
        "phase": phase.casefold(),
        "provider": "local_vllm",
        "endpoint_identity": endpoint,
        "model_id": benchmark.MODEL_ID,
        "dataset_manifest_sha256": dataset_contract_digest,
        "prompt_template_sha256": prompt_digest,
        "max_native_requests": request_count,
        "max_prompt_tokens": request_count * benchmark.PROMPT_TOKEN_BUDGET,
        "max_completion_tokens": request_count * benchmark.MAX_OUTPUT_TOKENS,
        "deadline": (now + timedelta(minutes=45)).isoformat(),
        "expires_at": (now + timedelta(minutes=55)).isoformat(),
        "synthetic_or_deidentified_only": True,
        "closed_test_access": phase == "CONFIRMATION",
    }
    manifest_path = run_dir / "provider-manifest.json"
    ledger_path = run_dir / "provider-ledger.jsonl"
    state._atomic_write(manifest_path, provider_manifest)
    state._atomic_write(
        run_dir / "benchmark-manifest.json",
        {
            "schema": "milai.dg10.lme-product-benchmark-manifest.v2",
            "run_id": run_id,
            "phase": phase,
            "arms": list(benchmark.ARMS),
            "source_case_ids": list(source_ids),
            "source_case_ids_sha256": source_ids_digest,
            "dataset_sha256": dataset_digest,
            "dataset_contract_sha256": dataset_contract_digest,
            "package_run_id": package_run_id,
            "package_artifacts": {
                name: package_artifacts[name] for name in sorted(required_packages)
            },
            "answer_model_calls_per_arm_case": 1,
            "max_native_requests": request_count,
            "memory_context_character_ceiling": benchmark.COMPACT_CONTEXT_CHARS,
            "memory_target_tokenizer_ceiling": benchmark.MEMORY_TOKEN_BUDGET,
            "confirmation_or_test_opened": phase == "CONFIRMATION",
            "development_ai_audits": 0,
        },
    )
    started = time.monotonic()
    status = "FAILED"
    error: str | None = None
    report: dict[str, Any] = {}
    command_trace: list[dict[str, Any]] = []
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
                trace=command_trace,
            )
            environment = dict(os.environ)
            environment.update(
                {
                    "DG10_MCP_HOST_PYTHON": install["python"],
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": str(ROOT),
                }
            )
            state._run(
                [
                    install["python"],
                    "-m",
                    "evals.benchmark.lme_product_worker",
                    "--env-file",
                    str(ROOT / "runtime/.env"),
                    "--dataset-path",
                    str(dataset),
                    "--provider-manifest",
                    str(manifest_path),
                    "--provider-ledger",
                    str(ledger_path),
                    "--provider-endpoint",
                    endpoint,
                    "--source-ids-json",
                    json.dumps(list(source_ids), separators=(",", ":")),
                    "--phase",
                    phase,
                    "--report",
                    str(run_dir / "report.json"),
                    "--sidecar",
                    str(run_dir / "raw-records.json"),
                ],
                cwd=Path(temporary).resolve(),
                env=environment,
                trace=command_trace,
                timeout=3_600,
            )
            report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            sidecar = json.loads(
                (run_dir / "raw-records.json").read_text(encoding="utf-8")
            )
            installed = report.get("installed_product") or {}
            installed_prefix = Path(str(installed.get("prefix", ""))).resolve()
            expected_prefix = Path(install["python"]).parent.parent.resolve()
            origins = installed.get("module_origins") or {}
            if (
                installed_prefix != expected_prefix
                or set(origins) != {"runtime", "client", "mcp", "openworker"}
                or any(
                    not Path(str(origin)).resolve().is_relative_to(expected_prefix)
                    for origin in origins.values()
                )
                or sidecar.get("schema") != "milai.dg10.lme-product-benchmark-raw.v2"
                or sidecar.get("run_id") != run_id
                or not isinstance(sidecar.get("records"), list)
                or len(sidecar["records"]) != len(source_ids) * len(benchmark.ARMS)
            ):
                raise state.F0Error("LongMemEval did not execute the installed product")
        if report.get("status") != "PASS_BASELINE_RECORDED":
            raise state.F0Error(f"LongMemEval {phase} did not record a complete run")
        status = "PASS"
    except Exception as exc:  # noqa: BLE001 - every benchmark denominator is recorded
        error = f"{type(exc).__name__}: {exc}"
    provider_ledger = _provider_ledger_summary(manifest_path, ledger_path)
    if status == "PASS" and provider_ledger["status"] != "VALID":
        status = "FAILED"
        error = f"provider ledger invalid: {provider_ledger['error']}"
    cases = {
        f"LME-{phase}-{index:02d}": (
            "PASS"
            if status == "PASS"
            and len(
                [
                    record
                    for record in report.get("records", [])
                    if record.get("case_id") == f"longmemeval:{source_ids[index - 1]}"
                ]
            )
            == len(benchmark.ARMS)
            else "FAILED"
        )
        for index in range(1, len(source_ids) + 1)
    }
    result = {
        "schema": "milai.dg10.benchmark-run-result.v1",
        "run_id": run_id,
        "status": status,
        "cases": cases,
        "phase": phase,
        "arms": list(benchmark.ARMS),
        "provider_requests": provider_ledger["native_requests_started"],
        "provider_ledger": provider_ledger,
        "aggregates": report.get("aggregates"),
        "deltas_vs_strongest_baseline": report.get("deltas_vs_strongest_baseline"),
        "category_deltas_vs_strongest_baseline": report.get(
            "category_deltas_vs_strongest_baseline"
        ),
        "quality_gates": report.get("quality_gates"),
        "quality_gate_status": report.get("quality_gate_status"),
        "development_ai_audits": 0,
        "duration_seconds": round(time.monotonic() - started, 6),
        "error": error,
        "finished_at": state._now(),
    }
    state._atomic_write(run_dir / "trace.json", {"commands": command_trace})
    state._atomic_write(run_dir / "result.json", result)
    experiment = {
        "experiment_id": f"exp-{run_id}",
        "run_id": run_id,
        "timestamp": result["finished_at"],
        "rm_id": "RM-14" if phase == "CONFIRMATION" else "RM-05",
        "rm_ids": (
            ["RM-05", "RM-08", "RM-14"]
            if phase == "CONFIRMATION"
            else ["RM-05", "RM-08"]
        ),
        "rm_statuses": {
            "RM-05": "PASS" if phase in {"DEV", "CONFIRMATION"} else "IN_PROGRESS",
            "RM-08": (
                "PASS"
                if phase == "CONFIRMATION"
                and status == "PASS"
                and report.get("quality_gate_status") == "PASS"
                else "IN_PROGRESS"
            ),
            **(
                {
                    "RM-14": (
                        "IN_PROGRESS"
                        if status == "PASS"
                        and report.get("quality_gate_status") == "PASS"
                        else "FAILED"
                    )
                }
                if phase == "CONFIRMATION"
                else {}
            ),
        },
        "hypothesis": (
            "the one-time frozen held-out split confirms the DEV quality gates without code, "
            "prompt, model, dataset, threshold, or product-package drift"
            if phase == "CONFIRMATION"
            else (
            "the frozen 50-case public DEV split can be measured through independent RAG and "
            "governed MiLAi retrieval with one answer call per arm"
            if phase == "DEV"
            else (
                "the product smoke can be measured fairly with independent RAG and governed "
                "MiLAi retrieval and exactly one answer call per arm"
            )
            )
        ),
        "code_identity": state._tree_identity(
            [
                ROOT / "evals/benchmark/lme_product_smoke.py",
                ROOT / "evals/benchmark/lme_product_worker.py",
                ROOT / "scripts/run_dg10_lme_product_dev.py",
                Path(__file__).resolve(),
            ]
        ),
        "model_identity": benchmark.MODEL_ID,
        "dataset_identity": dataset_contract_digest,
        "prompt_identity": prompt_digest,
        "budget": {
            "native_requests": request_count,
            "prompt_tokens": request_count * benchmark.PROMPT_TOKEN_BUDGET,
            "completion_tokens": request_count * benchmark.MAX_OUTPUT_TOKENS,
        },
        "expected_delta": (
            "overall, knowledge-update and temporal F1/EM non-inferior; memory <=512; prompt <=2x"
            if phase in {"DEV", "CONFIRMATION"}
            else "record the current three-arm product smoke"
        ),
        "functional_gate": f"LME_{phase}",
        "functional_cases_passed": [
            case for case, value in cases.items() if value == "PASS"
        ],
        "functional_cases_failed": [
            case for case, value in cases.items() if value != "PASS"
        ],
        "actual_quality_delta": (result.get("deltas_vs_strongest_baseline") or {}).get(
            "normalized_f1"
        ),
        "actual_token_delta": (result.get("deltas_vs_strongest_baseline") or {}).get(
            "prompt_tokens_mean"
        ),
        "actual_latency_delta": (result.get("deltas_vs_strongest_baseline") or {}).get(
            "total_latency_ms_mean"
        ),
        "prepare_context_calls": len(source_ids),
        "full_recall_calls": len(source_ids),
        "cache_validation_calls": 0,
        "validated_cache_hit_rate": None,
        "relevant_issue_misses": 0,
        "irrelevant_issue_injections": 0,
        "action_revalidation_failures": 0,
        "degraded_or_abstain_count": sum(
            record.get("memory_status") != "AVAILABLE"
            for record in report.get("records", [])
            if record.get("arm") == "MILAI_T3A"
        ),
        "status": status,
        "decision": (
            "KEEP"
            if phase in {"DEV", "CONFIRMATION"}
            and report.get("quality_gate_status") == "PASS"
            else ("BASELINE_ONLY" if phase == "SMOKE" else "REDESIGN")
        ),
        "next_action": (
            "materialize the final report and single frozen candidate bundle"
            if phase == "CONFIRMATION"
            and report.get("quality_gate_status") == "PASS"
            else (
            "run controlled-availability and remaining integration gates"
            if phase == "DEV" and report.get("quality_gate_status") == "PASS"
            else "classify the largest failing DEV category before changing one mechanism"
            )
        ),
    }
    state._record_run(result, experiment)
    return result


def run_smoke(
    run_id: str,
    package_run_id: str,
    *,
    dataset: Path = DEFAULT_DATASET,
    endpoint: str = ENDPOINT,
) -> dict[str, Any]:
    return run_benchmark(
        run_id,
        package_run_id,
        phase="SMOKE",
        source_ids=benchmark.SMOKE_SOURCE_IDS,
        dataset=dataset,
        endpoint=endpoint,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DG-10 product-path LME smoke")
    parser.add_argument(
        "--run-id",
        default=(
            "lme-smoke-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        ),
    )
    parser.add_argument("--package-run-id", required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--endpoint", default=ENDPOINT)
    args = parser.parse_args()
    result = run_smoke(
        args.run_id,
        args.package_run_id,
        dataset=args.dataset.resolve(),
        endpoint=args.endpoint,
    )
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "provider_requests": result["provider_requests"],
                "aggregates": result["aggregates"],
                "deltas": result["deltas_vs_strongest_baseline"],
            },
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
