from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from milai.adapters.agent_prefetch import PrefetchContext
from milai.adapters.provider_execution import (
    JsonCompletionTransport,
    ProviderExecutionGateway,
    ProviderRequest,
)

from evals.benchmark import dg11_holdout
from evals.benchmark import lme_product_smoke as benchmark
from scripts import dg11_state, freeze_dg11_holdout
from scripts import run_dg10_f0 as f0

DEFAULT_FREEZE = ROOT / "var/dg11/holdout/v1/freeze-manifest.json"
DEFAULT_ENDPOINT = "http://127.0.0.1:7860"
DEFAULT_ENV_FILE = ROOT / "runtime/.env"
CURRENT_PYTHON = ROOT / "runtime/.venv/bin/python"
RUNS_ROOT = ROOT / "var/dg11/runs"
_RUN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{7,95}")


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise dg11_holdout.HoldoutError(f"expected JSON object: {path}")
    return value


def _resolve_bound_path(raw: object) -> Path:
    if not isinstance(raw, str):
        raise dg11_holdout.HoldoutError("frozen path is invalid")
    path = (ROOT / raw).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise dg11_holdout.HoldoutError("frozen path escaped or is absent")
    return path


def _validate_freeze(path: Path) -> tuple[dict[str, Any], Path]:
    frozen = _load_object(path)
    if (
        frozen.get("schema") != "milai.dg11.holdout-freeze.v1"
        or frozen.get("status") != "FROZEN"
        or frozen.get("case_count") != dg11_holdout.CASE_COUNT
        or frozen.get("arms") != list(dg11_holdout.ARMS)
        or frozen.get("native_answer_requests") != 400
        or frozen.get("labels_opened") is not False
        or frozen.get("label_fields_in_inputs") is not False
        or frozen.get("prompt_contract_sha256") != benchmark.prompt_contract_sha256()
        or frozen.get("model_id") != benchmark.MODEL_ID
        or frozen.get("memory_token_budget") != benchmark.MEMORY_TOKEN_BUDGET
        or frozen.get("code_identity") != freeze_dg11_holdout.code_identity()
    ):
        raise dg11_holdout.HoldoutError("DG11 holdout freeze manifest drifted")
    inputs_path = _resolve_bound_path(frozen.get("holdout_inputs_path"))
    if dg11_state.sha256(inputs_path) != frozen.get("holdout_inputs_sha256"):
        raise dg11_holdout.HoldoutError("label-free holdout inputs drifted")
    inputs = _load_object(inputs_path)
    if (
        inputs.get("label_fields_present") is not False
        or inputs.get("source_ids") != frozen.get("source_ids")
        or dg11_holdout.digest(tuple(inputs["source_ids"]))
        != frozen.get("source_ids_sha256")
        or dg11_holdout.allocation_from_inputs(inputs)
        != frozen.get("category_allocation")
    ):
        raise dg11_holdout.HoldoutError("label-free holdout input contract drifted")
    for name, entry in frozen["dg10_frozen_wheels"].items():
        wheel = _resolve_bound_path(entry.get("path"))
        if dg11_state.sha256(wheel) != entry.get("sha256"):
            raise dg11_holdout.HoldoutError(f"frozen DG10 wheel drifted: {name}")
    return frozen, inputs_path


def _consume(frozen: dict[str, Any], run_id: str, freeze_path: Path) -> None:
    consumption = ROOT / str(frozen["consumption_path"])
    consumption = consumption.resolve()
    expected_parent = freeze_path.resolve().parent
    if consumption.parent != expected_parent:
        raise dg11_holdout.HoldoutError("holdout consumption path drifted")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(consumption, flags, 0o600)
    except FileExistsError as exc:
        raise dg11_holdout.HoldoutError("DG11 sealed holdout was already consumed") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "schema": "milai.dg11.holdout-consumption.v1",
                "run_id": run_id,
                "freeze_manifest_sha256": dg11_state.sha256(freeze_path),
                "consumed_at": datetime.now(UTC).isoformat(),
                "new_attempts_on_same_split_allowed": False,
            },
            handle,
            sort_keys=True,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _context(value: dict[str, Any]) -> PrefetchContext:
    return PrefetchContext(
        status=value["status"],
        rendered=str(value["rendered"]),
        context_sha256=str(value["context_sha256"]),
        trace_id=None,
        request_id=None,
        claim_refs=(),
        evidence_refs=(),
        open_issue_ids=(),
        degraded_components=(),
        abstention_reason=None,
    )


def _prepare_contexts(
    *,
    frozen: dict[str, Any],
    inputs_path: Path,
    run_dir: Path,
    env_file: Path,
    install_root: Path,
    trace: list[dict[str, Any]],
    expected_cases: int = dg11_holdout.CASE_COUNT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    wheels = {
        name: _resolve_bound_path(entry["path"])
        for name, entry in frozen["dg10_frozen_wheels"].items()
    }
    install = f0._probe_install(
        kind="wheel",
        client_artifact=wheels["client_wheel"],
        mcp_artifact=wheels["mcp_wheel"],
        runtime_artifact=wheels["runtime_wheel"],
        runtime_extras=("embedding",),
        openworker_artifact=wheels["openworker_wheel"],
        workspace=install_root,
        trace=trace,
    )
    frozen_env_file = install_root.parent / "dg10-frozen.env"
    frozen_env_file.write_text(
        "\n".join(
            line
            for line in env_file.read_text(encoding="utf-8").splitlines()
            if not line.startswith("MILAI_EMBEDDING_PROJECTION_DIMENSIONS=")
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(frozen_env_file, 0o600)
    current_mcp_python = ROOT / "integrations/mcp/.venv/bin/python"
    if not current_mcp_python.is_file():
        raise dg11_holdout.HoldoutError("current MCP host environment is absent")
    jobs = (
        (
            "frozen",
            Path(install["python"]),
            Path(install["python"]),
            frozen_env_file,
            run_dir / "contexts-dg10-frozen.json",
        ),
        (
            "current",
            CURRENT_PYTHON,
            current_mcp_python,
            env_file,
            run_dir / "contexts-dg11-current.json",
        ),
    )
    processes: list[tuple[str, subprocess.Popen[bytes], Path]] = []
    for identity, python, mcp_python, worker_env_file, output in jobs:
        environment = dict(os.environ)
        environment.update(
            {
                "DG10_MCP_HOST_PYTHON": str(mcp_python),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(ROOT),
            }
        )
        command = [
            str(python),
            "-m",
            "evals.benchmark.dg11_holdout_context_worker",
            "--inputs",
            str(inputs_path),
            "--output",
            str(output),
            "--env-file",
            str(worker_env_file),
            "--identity",
            identity,
            "--workers",
            "1",
            "--expected-cases",
            str(expected_cases),
        ]
        processes.append(
            (identity, subprocess.Popen(command, cwd=ROOT, env=environment), output)
        )
        trace.append({"argv": command, "identity": identity})
    failures: list[str] = []
    for identity, process, _output in processes:
        returncode = process.wait()
        if returncode != 0:
            failures.append(f"{identity}:{returncode}")
    if failures:
        raise dg11_holdout.HoldoutError(
            "parallel context preparation failed: " + ", ".join(failures)
        )
    outputs = {identity: _load_object(output) for identity, _process, output in processes}
    for identity, output in outputs.items():
        if (
            output.get("schema") != "milai.dg11.holdout-contexts.v1"
            or output.get("identity") != identity
            or not isinstance(output.get("records"), list)
            or len(output["records"]) != expected_cases
        ):
            raise dg11_holdout.HoldoutError(f"{identity} context output drifted")
    return outputs["frozen"], outputs["current"]


def _labels(dataset: Path, source_ids: set[str]) -> dict[str, list[str]]:
    rows = json.loads(dataset.read_text(encoding="utf-8"))
    labels = {
        str(row["question_id"]): benchmark.scoring._answer_values(row["answer"])
        for row in rows
        if isinstance(row, dict) and row.get("question_id") in source_ids
    }
    if set(labels) != source_ids:
        raise dg11_holdout.HoldoutError("sealed holdout labels are incomplete")
    return labels


def _supporting_safety_pass() -> bool:
    functional = _load_object(ROOT / "var/dg11/functional/latest-result.json")
    agentic = _load_object(ROOT / "var/dg11/agentic/latest-result.json")
    functional_gates = (functional.get("classification") or {}).get("gates") or {}
    agentic_gates = agentic.get("gates") or {}
    return (
        functional.get("status") == "PASS"
        and functional_gates.get("canonical_mutation_semantics_unchanged") is True
        and functional_gates.get("secret_private_content_leakage_zero") is True
        and agentic.get("status") == "PASS"
        and agentic_gates.get("wrong_certain_actions_zero") is True
        and agentic_gates.get("stale_revoked_actions_zero") is True
    )


def run(
    run_id: str,
    *,
    freeze_path: Path,
    endpoint: str,
    env_file: Path,
) -> dict[str, Any]:
    if _RUN_ID.fullmatch(run_id) is None:
        raise dg11_holdout.HoldoutError("run_id must be 8-96 lowercase URL-safe characters")
    if not CURRENT_PYTHON.is_file():
        raise dg11_holdout.HoldoutError("current Runtime environment is absent")
    frozen, inputs_path = _validate_freeze(freeze_path)
    dataset = Path(str(frozen["dataset_path"])).resolve()
    if not dataset.is_file() or dg11_state.sha256(dataset) != frozen["dataset_sha256"]:
        raise dg11_holdout.HoldoutError("LongMemEval dataset drifted after freeze")
    run_dir = RUNS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    os.chmod(run_dir, 0o700)
    _consume(frozen, run_id, freeze_path)
    started = time.monotonic()
    command_trace: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix=f"milai-{run_id}-") as temporary:
        dg10_contexts, dg11_contexts = _prepare_contexts(
            frozen=frozen,
            inputs_path=inputs_path,
            run_dir=run_dir,
            env_file=env_file,
            install_root=Path(temporary) / "dg10-product",
            trace=command_trace,
        )
    inputs = _load_object(inputs_path)
    raw_cases = inputs["cases"]
    dg10_by_id = {record["source_id"]: record for record in dg10_contexts["records"]}
    dg11_by_id = {record["source_id"]: record for record in dg11_contexts["records"]}

    now = datetime.now(UTC)
    provider_manifest = {
        "schema": "milai.provider.closed-test-run.v1",
        "run_id": run_id,
        "phase": "confirmation",
        "provider": "local_vllm",
        "endpoint_identity": endpoint,
        "model_id": benchmark.MODEL_ID,
        "dataset_manifest_sha256": dg11_state.sha256(freeze_path),
        "prompt_template_sha256": benchmark.prompt_contract_sha256(),
        "max_native_requests": 400,
        "max_prompt_tokens": 400 * benchmark.PROMPT_TOKEN_BUDGET,
        "max_completion_tokens": 400 * benchmark.MAX_OUTPUT_TOKENS,
        "deadline": (now + timedelta(minutes=90)).isoformat(),
        "expires_at": (now + timedelta(minutes=100)).isoformat(),
        "synthetic_or_deidentified_only": True,
        "closed_test_access": True,
    }
    manifest_path = run_dir / "provider-manifest.json"
    ledger_path = run_dir / "provider-ledger.jsonl"
    dg11_state.atomic_json(manifest_path, provider_manifest)
    dg11_state.atomic_json(
        run_dir / "benchmark-manifest.json",
        {
            "schema": "milai.dg11.holdout-run-manifest.v1",
            "run_id": run_id,
            "freeze_manifest_sha256": dg11_state.sha256(freeze_path),
            "arms": list(dg11_holdout.ARMS),
            "case_count": 100,
            "native_answer_requests": 400,
            "answer_calls_per_arm_case": 1,
            "hidden_calls": 0,
            "labels_opened_before_generation": False,
            "runtime_parallelism": {
                "total_processes": 2,
                "workers_per_process": 1,
            },
        },
    )
    gateway = ProviderExecutionGateway(manifest_path, ledger_path)
    transport = JsonCompletionTransport()
    generation_records: list[dict[str, Any]] = []
    for case_index, raw in enumerate(raw_cases):
        case = dg11_holdout.product_case(raw)
        rag_context, _rag_ids, rag_ms = benchmark._rag_context(case)
        contexts = {
            "NO_MEMORY": PrefetchContext.no_memory(),
            "NAIVE_RAG": rag_context,
            "MILAI_DG10_FROZEN": _context(dg10_by_id[case.source_case_id]["context"]),
            "MILAI_DG11_CURRENT": _context(dg11_by_id[case.source_case_id]["context"]),
        }
        retrieval_ms = {
            "NO_MEMORY": 0.0,
            "NAIVE_RAG": rag_ms,
            "MILAI_DG10_FROZEN": float(
                dg10_by_id[case.source_case_id]["trace"]["mcp_recall_ms"]
            ),
            "MILAI_DG11_CURRENT": float(
                dg11_by_id[case.source_case_id]["trace"]["mcp_recall_ms"]
            ),
        }
        messages = {
            arm: benchmark._messages(case.question, case.question_at, context)
            for arm, context in contexts.items()
        }
        prompt_tokens = {
            arm: benchmark._count_prompt_tokens(endpoint, value)
            for arm, value in messages.items()
        }
        no_memory_tokens = prompt_tokens["NO_MEMORY"]
        memory_tokens = {
            arm: max(0, tokens - no_memory_tokens)
            for arm, tokens in prompt_tokens.items()
        }
        if any(value > benchmark.MEMORY_TOKEN_BUDGET for value in memory_tokens.values()):
            raise dg11_holdout.HoldoutError("a holdout arm exceeds 512 memory tokens")
        frozen_schedule = dg11_holdout.schedule(case_index)
        for arm in frozen_schedule:
            logical_id = f"{run_id}-{case_index + 1:03d}-{arm.casefold()}"
            call_started = time.perf_counter()
            completion = gateway.execute(
                ProviderRequest(
                    logical_request_id=logical_id,
                    transport="json",
                    payload=benchmark._payload(
                        messages[arm], dg11_holdout.generation_id(case_index, arm)
                    ),
                    prompt_token_budget=benchmark.PROMPT_TOKEN_BUDGET,
                    completion_token_budget=benchmark.MAX_OUTPUT_TOKENS,
                    timeout_seconds=180,
                ),
                transport,
                benchmark._parse,
            )
            if completion.prompt_tokens != prompt_tokens[arm]:
                raise dg11_holdout.HoldoutError(
                    "target tokenizer recount differs from native usage"
                )
            generation_records.append(
                {
                    "source_id": case.source_case_id,
                    "case_id": case.case_id,
                    "category": case.category,
                    "arm": arm,
                    "schedule": list(frozen_schedule),
                    "answer": str(completion.value),
                    "answer_sha256": hashlib.sha256(
                        str(completion.value).encode()
                    ).hexdigest(),
                    "prompt_tokens": completion.prompt_tokens,
                    "completion_tokens": completion.completion_tokens,
                    "memory_tokens": memory_tokens[arm],
                    "memory_context_chars": len(contexts[arm].rendered),
                    "context_sha256": contexts[arm].context_sha256,
                    "retrieval_latency_ms": round(retrieval_ms[arm], 3),
                    "answer_latency_ms": round(
                        (time.perf_counter() - call_started) * 1000, 3
                    ),
                    "native_request_id": completion.native_request_id,
                    "model_calls": 1,
                    "hidden_model_calls": 0,
                }
            )
            dg11_state.atomic_json(
                run_dir / "sealed-generations.json",
                {
                    "schema": "milai.dg11.holdout-generations.v1",
                    "labels_opened": False,
                    "records": generation_records,
                },
            )
        print(
            json.dumps(
                {"phase": "generation", "completed_cases": case_index + 1, "total": 100},
                sort_keys=True,
            ),
            flush=True,
        )

    events = gateway.read_ledger()
    reservations = [event for event in events if event.get("event") == "RESERVED"]
    terminals = [event for event in events if event.get("event") == "PROVIDER_TERMINAL"]
    post = [event for event in events if event.get("event") == "POST_PROVIDER_TERMINAL"]
    denominator_valid = (
        len(generation_records) == 400
        and len(reservations) == 400
        and len(terminals) == 400
        and len(post) == 400
        and all(event.get("status") == "SUCCEEDED" for event in terminals + post)
        and len({event.get("native_request_id") for event in terminals}) == 400
    )
    if not denominator_valid:
        raise dg11_holdout.HoldoutError("sealed provider denominator is incomplete")

    # This is the first label access: all 400 answers and provider terminals are sealed.
    labels = _labels(dataset, set(frozen["source_ids"]))
    scored = dg11_holdout.score_records(generation_records, labels)
    v1 = scored["arms"]
    current = v1["MILAI_DG11_CURRENT"]["scorer_v1"]
    dg10 = v1["MILAI_DG10_FROZEN"]["scorer_v1"]
    fixed_baseline_name = max(
        ("NO_MEMORY", "NAIVE_RAG"),
        key=lambda arm: v1[arm]["scorer_v1"]["normalized_f1_mean"],
    )
    fixed = v1[fixed_baseline_name]["scorer_v1"]
    rag = v1["NAIVE_RAG"]["scorer_v1"]
    paired = scored["paired"]["scorer_v1"]
    assistant_delta = dg11_holdout.category_delta(
        scored, "single-session-assistant", "MILAI_DG11_CURRENT", "NAIVE_RAG"
    )
    preference_delta = dg11_holdout.category_delta(
        scored, "single-session-preference", "MILAI_DG11_CURRENT", "NAIVE_RAG"
    )
    temporal_delta = dg11_holdout.category_delta(
        scored, "temporal-reasoning", "MILAI_DG11_CURRENT", "MILAI_DG10_FROZEN"
    )
    prompt_ratio = round(
        float(current["prompt_tokens_mean"])
        / max(1.0, float(rag["prompt_tokens_mean"])),
        6,
    )
    safety_failures = 0 if _supporting_safety_pass() else 1
    gates = {
        "dg11_minus_dg10_paired_f1_gte_0_04": paired["dg11_minus_dg10_f1_mean"]
        >= 0.04,
        "dg11_minus_dg10_bootstrap_lower95_gt_zero": paired["bootstrap"]["lower95"]
        > 0,
        "dg11_minus_dg10_em_gte_zero": float(current["exact_match_mean"])
        - float(dg10["exact_match_mean"])
        >= 0,
        "dg11_minus_strongest_fixed_baseline_f1_gte_0_10": float(
            current["normalized_f1_mean"]
        )
        - float(fixed["normalized_f1_mean"])
        >= 0.10,
        "single_assistant_delta_vs_rag_gte_zero": assistant_delta >= 0,
        "preference_delta_vs_rag_gte_zero": preference_delta >= 0,
        "temporal_delta_vs_dg10_gt_zero": temporal_delta > 0,
        "prompt_token_ratio_vs_rag_lte_1_20": prompt_ratio <= 1.20,
        "safety_failures_zero": safety_failures == 0,
        "provider_denominator_400": denominator_valid,
        "one_answer_call_per_arm_case": all(
            record["model_calls"] == 1 for record in generation_records
        ),
        "hidden_calls_zero": all(
            record["hidden_model_calls"] == 0 for record in generation_records
        ),
    }
    passed = all(gates.values())
    result = {
        "schema": "milai.dg11.holdout-result.v1",
        "run_id": run_id,
        "work_package": "DG11-09",
        "status": "PASS" if passed else "HOLDOUT_FAILED",
        "decision": "KEEP" if passed else "RETURN_TO_DEVELOPMENT_NEW_SPLIT_REQUIRED",
        "case_count": 100,
        "provider_requests": 400,
        "hidden_provider_calls": 0,
        "labels_opened_after_generation": True,
        "holdout_reusable": False,
        "development_ai_reviews": 0,
        "scorers": {"v1": "LEGACY_DG10", "v2": "DG11_NORMALIZED"},
        "aggregates": scored["arms"],
        "category_aggregates": scored["categories"],
        "paired": scored["paired"],
        "summary": {
            "dg11_minus_dg10_f1": paired["dg11_minus_dg10_f1_mean"],
            "dg11_minus_dg10_bootstrap_lower95": paired["bootstrap"]["lower95"],
            "dg11_minus_dg10_em": round(
                float(current["exact_match_mean"]) - float(dg10["exact_match_mean"]),
                6,
            ),
            "strongest_fixed_baseline": fixed_baseline_name,
            "dg11_minus_strongest_fixed_baseline_f1": round(
                float(current["normalized_f1_mean"])
                - float(fixed["normalized_f1_mean"]),
                6,
            ),
            "single_assistant_delta_vs_rag": assistant_delta,
            "preference_delta_vs_rag": preference_delta,
            "temporal_delta_vs_dg10": temporal_delta,
            "prompt_token_ratio_vs_rag": prompt_ratio,
            "safety_failures": safety_failures,
        },
        "gates": gates,
        "provider_trace": {
            "reservations": len(reservations),
            "provider_terminals": len(terminals),
            "post_provider_terminals": len(post),
            "unique_native_ids": len(
                {event.get("native_request_id") for event in terminals}
            ),
        },
        "freeze_manifest_sha256": dg11_state.sha256(freeze_path),
        "duration_seconds": round(time.monotonic() - started, 3),
        "finished_at": datetime.now(UTC).isoformat(),
    }
    dg11_state.atomic_json(run_dir / "scored-records.json", scored)
    dg11_state.atomic_json(run_dir / "trace.json", {"commands": command_trace})
    dg11_state.atomic_json(run_dir / "result.json", result)
    dg11_state.record_result(
        result,
        phase="HOLDOUT_PASSED" if passed else "HOLDOUT_FAILED",
        work_package="DG11-09",
        state_status="PASS" if passed else "HOLDOUT_FAILED",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the one-time DG11 sealed holdout")
    parser.add_argument("run_id")
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    args = parser.parse_args()
    result = run(
        args.run_id,
        freeze_path=args.freeze.resolve(),
        endpoint=args.endpoint,
        env_file=args.env_file.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
