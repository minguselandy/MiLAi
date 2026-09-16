from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
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

from evals.benchmark import dg11_holdout, dg11_v2
from evals.benchmark import lme_product_smoke as benchmark
from scripts import dg11_state, freeze_dg11_v2
from scripts import run_dg10_f0 as package_gate

DEFAULT_FREEZE = ROOT / "var/dg11/holdout/v2/freeze-manifest.json"
DEFAULT_ENDPOINT = "http://127.0.0.1:7860"
DEFAULT_ENV_FILE = ROOT / "runtime/.env"
RUNS_ROOT = ROOT / "var/dg11/runs"
ANSWER_WORKERS = 2
DG10_INCOMPATIBLE_ENV_KEYS = frozenset(
    {
        "MILAI_EMBEDDING_PROJECTION_DIMENSIONS",
        "MILAI_RETRIEVAL_RERANKER_PROVIDER",
        "MILAI_RETRIEVAL_RERANKER_MODEL_PATH",
        "MILAI_RETRIEVAL_RERANKER_MODEL_ID",
        "MILAI_RETRIEVAL_RERANKER_REVISION",
        "MILAI_RETRIEVAL_RERANKER_MODEL_SHA256",
        "MILAI_RETRIEVAL_RERANKER_POOL_SIZE",
        "MILAI_RETRIEVAL_TEMPORAL_RERANKER_POOL_SIZE",
    }
)


class V2RunError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V2RunError(f"required JSON is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise V2RunError(f"required JSON is not an object: {path}")
    return value


def _env_key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    if stripped.startswith("export "):
        stripped = stripped.removeprefix("export ").lstrip()
    key, _separator, _value = stripped.partition("=")
    return key.strip()


def _dg10_compatible_env(value: str) -> tuple[str, tuple[str, ...]]:
    removed: set[str] = set()
    retained: list[str] = []
    for line in value.splitlines():
        key = _env_key(line)
        if key in DG10_INCOMPATIBLE_ENV_KEYS:
            assert key is not None
            removed.add(key)
            continue
        retained.append(line)
    if removed != DG10_INCOMPATIBLE_ENV_KEYS:
        missing = sorted(DG10_INCOMPATIBLE_ENV_KEYS - removed)
        raise V2RunError(
            "frozen DG11 config is missing the expected DG10-incompatible keys: "
            + ", ".join(missing)
        )
    return "\n".join(retained) + "\n", tuple(sorted(removed))


def _validate_candidate_config(frozen: Mapping[str, Any], env_file: Path) -> None:
    candidate = _load(_bound_path(frozen.get("candidate_manifest_path")))
    config = candidate.get("config")
    if (
        not isinstance(config, Mapping)
        or not isinstance(config.get("sha256"), str)
        or dg11_state.sha256(env_file) != config.get("sha256")
    ):
        raise V2RunError("V2 runtime config differs from the frozen candidate")


def _bound_path(raw: object) -> Path:
    if not isinstance(raw, str):
        raise V2RunError("frozen path is invalid")
    path = Path(raw)
    path = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if not path.is_file():
        raise V2RunError(f"frozen path is absent: {path}")
    return path


def _validate_freeze(path: Path) -> tuple[dict[str, Any], Path, Path]:
    frozen = _load(path)
    candidate_path = _bound_path(frozen.get("candidate_manifest_path"))
    candidate = _load(candidate_path)
    if (
        frozen.get("schema") != "milai.dg11.generalization-v2-freeze.v1"
        or frozen.get("status") != "FROZEN"
        or frozen.get("case_count") != dg11_v2.CASE_COUNT
        or frozen.get("arms") != list(dg11_v2.ARMS)
        or frozen.get("native_answer_requests") != 400
        or frozen.get("answer_calls_per_arm_case") != 1
        or frozen.get("hidden_answer_calls") != 0
        or frozen.get("labels_opened") is not False
        or frozen.get("prompt_contract_sha256") != benchmark.prompt_contract_sha256()
        or frozen.get("model_id") != benchmark.MODEL_ID
        or frozen.get("memory_token_budget") != benchmark.MEMORY_TOKEN_BUDGET
        or frozen.get("max_output_tokens") != benchmark.MAX_OUTPUT_TOKENS
        or frozen.get("schedule_sha256") != dg11_v2.schedule_identity()
        or frozen.get("code_identity") != freeze_dg11_v2.code_identity()
        or frozen.get("candidate_manifest_sha256")
        != dg11_state.sha256(candidate_path)
        or frozen.get("candidate_id") != candidate.get("candidate_id")
        or candidate.get("status") != "FROZEN"
    ):
        raise V2RunError("V2 freeze manifest drifted")
    inputs = _bound_path(frozen.get("inputs_path"))
    dataset = _bound_path(frozen.get("dataset_path"))
    if (
        dg11_state.sha256(inputs) != frozen.get("inputs_sha256")
        or dg11_state.sha256(dataset) != frozen.get("dataset_sha256")
    ):
        raise V2RunError("V2 input or dataset identity drifted")
    payload = _load(inputs)
    if (
        payload.get("label_fields_present") is not False
        or len(payload.get("cases", [])) != dg11_v2.CASE_COUNT
        or dg11_holdout.digest(tuple(payload.get("source_ids", [])))
        != frozen.get("source_ids_sha256")
    ):
        raise V2RunError("V2 label-free input contract drifted")
    for group in ("dg10_frozen_wheels", "dg11_frozen_wheels"):
        entries = frozen.get(group)
        if not isinstance(entries, Mapping) or set(entries) != {
            "client_wheel",
            "mcp_wheel",
            "runtime_wheel",
            "openworker_wheel",
        }:
            raise V2RunError(f"V2 wheel group is incomplete: {group}")
        for entry in entries.values():
            if not isinstance(entry, Mapping):
                raise V2RunError(f"V2 wheel entry is malformed: {group}")
            wheel = _bound_path(entry.get("path"))
            if dg11_state.sha256(wheel) != entry.get("sha256"):
                raise V2RunError(f"V2 wheel identity drifted: {group}")
    return frozen, inputs, dataset


def _consume(frozen: Mapping[str, Any], run_id: str, freeze_path: Path) -> None:
    raw = frozen.get("consumption_path")
    if not isinstance(raw, str):
        raise V2RunError("V2 consumption path is invalid")
    path = (ROOT / raw).resolve()
    if path.parent != freeze_path.resolve().parent:
        raise V2RunError("V2 consumption path escaped the freeze directory")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise V2RunError("DG11 generalization V2 was already consumed") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "schema": "milai.dg11.generalization-v2-consumption.v1",
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


def _context(value: Mapping[str, Any]) -> PrefetchContext:
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
        compiler_version=str(value.get("compiler_version") or "UNRECORDED"),
    )


def _wheel_paths(frozen: Mapping[str, Any], group: str) -> dict[str, Path]:
    entries = frozen[group]
    assert isinstance(entries, Mapping)
    return {
        str(name): _bound_path(entry["path"])
        for name, entry in entries.items()
        if isinstance(entry, Mapping)
    }


def _prepare_contexts(
    *,
    frozen: Mapping[str, Any],
    inputs: Path,
    env_file: Path,
    run_root: Path,
    temporary_root: Path,
    trace: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    installs: dict[str, dict[str, Any]] = {}
    for identity, group in (
        ("dg10", "dg10_frozen_wheels"),
        ("dg11", "dg11_frozen_wheels"),
    ):
        wheels = _wheel_paths(frozen, group)
        installs[identity] = package_gate._probe_install(
            kind=f"{identity}-wheel",
            client_artifact=wheels["client_wheel"],
            mcp_artifact=wheels["mcp_wheel"],
            runtime_artifact=wheels["runtime_wheel"],
            runtime_extras=("embedding",),
            openworker_artifact=wheels["openworker_wheel"],
            workspace=temporary_root / identity,
            trace=trace,
        )
    dg10_env = temporary_root / "dg10.env"
    dg10_env_value, removed_keys = _dg10_compatible_env(
        env_file.read_text(encoding="utf-8")
    )
    dg10_env.write_text(dg10_env_value, encoding="utf-8")
    os.chmod(dg10_env, 0o600)
    trace.append(
        {
            "identity": "dg10",
            "config_derivation": "DROP_DG11_ONLY_KEYS",
            "source_env_sha256": dg11_state.sha256(env_file),
            "removed_keys": list(removed_keys),
        }
    )
    jobs = (
        ("dg10", dg10_env, run_root / "contexts-dg10-frozen.json"),
        ("dg11", env_file, run_root / "contexts-dg11-frozen.json"),
    )
    processes: list[tuple[str, subprocess.Popen[bytes], Path]] = []
    for identity, worker_env, output in jobs:
        python = Path(str(installs[identity]["python"]))
        environment = dict(os.environ)
        environment.update(
            {
                "DG10_MCP_HOST_PYTHON": str(python),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(ROOT),
            }
        )
        command = [
            str(python),
            "-m",
            "evals.benchmark.dg11_holdout_context_worker",
            "--inputs",
            str(inputs),
            "--output",
            str(output),
            "--env-file",
            str(worker_env),
            "--identity",
            "frozen",
            "--workers",
            "1",
            "--expected-cases",
            str(dg11_v2.CASE_COUNT),
            "--max-case-attempts",
            "3",
        ]
        processes.append(
            (identity, subprocess.Popen(command, cwd=ROOT, env=environment), output)
        )
        trace.append({"identity": identity, "command": command})
    failures: list[str] = []
    for identity, process, _output in processes:
        returncode = process.wait()
        if returncode != 0:
            failures.append(f"{identity}:{returncode}")
    if failures:
        raise V2RunError("V2 context preparation failed: " + ", ".join(failures))
    outputs = {
        identity: _load(context_path)
        for identity, _process, context_path in processes
    }
    for identity, output_payload in outputs.items():
        if len(output_payload.get("records", [])) != dg11_v2.CASE_COUNT:
            raise V2RunError(f"V2 {identity} context denominator drifted")
    return outputs["dg10"], outputs["dg11"]


def _labels(dataset: Path, source_ids: set[str]) -> dict[str, list[str]]:
    rows = json.loads(dataset.read_text(encoding="utf-8"))
    labels = {
        str(row["question_id"]): benchmark.scoring._answer_values(row["answer"])
        for row in rows
        if isinstance(row, dict) and row.get("question_id") in source_ids
    }
    if set(labels) != source_ids:
        raise V2RunError("V2 sealed labels are incomplete")
    return labels


def _supporting_safety_pass() -> bool:
    functional = _load(ROOT / "var/dg11/functional/latest-result.json")
    agentic = _load(ROOT / "var/dg11/agentic/latest-result.json")
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


def _retrieval_ms(record: Mapping[str, Any]) -> float:
    trace = record.get("trace")
    if not isinstance(trace, Mapping):
        return 0.0
    value = trace.get("retrieval_ms", trace.get("mcp_recall_ms", 0.0))
    return float(value) if isinstance(value, int | float) else 0.0


def _record_state(result: Mapping[str, Any]) -> None:
    state = _load(dg11_state.CURRENT_STATE)
    recovery = state.setdefault("recovery_work_packages", {})
    if not isinstance(recovery, dict):
        raise V2RunError("recovery work-package state is malformed")
    recovery["DG11-09V2"] = str(result["status"])
    state["recovery_phase"] = "V2_CONSUMED"
    state["latest_result"] = result["run_id"]
    state["development_ai_reviews"] = 0
    dg11_state.atomic_json(dg11_state.CURRENT_STATE, state)
    dg11_state.append_ledger(
        {
            "run_id": result["run_id"],
            "work_package": "DG11-09V2",
            "status": result["status"],
            "decision": result["decision"],
            "provider_requests": 400,
            "development_ai_reviews": 0,
            "metrics": result["summary"],
        }
    )


def run(
    run_id: str,
    *,
    freeze_path: Path = DEFAULT_FREEZE,
    endpoint: str = DEFAULT_ENDPOINT,
    env_file: Path = DEFAULT_ENV_FILE,
) -> dict[str, Any]:
    if package_gate._RUN_ID.fullmatch(run_id) is None:
        raise V2RunError("run_id must be 8-96 lowercase URL-safe characters")
    frozen, inputs_path, dataset = _validate_freeze(freeze_path)
    _validate_candidate_config(frozen, env_file)
    run_root = RUNS_ROOT / run_id
    try:
        run_root.mkdir(parents=True, mode=0o700)
    except FileExistsError as exc:
        raise V2RunError(f"run_id already exists: {run_id}") from exc
    started = time.monotonic()
    trace: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix=f"milai-{run_id}-") as temporary:
        dg10_payload, dg11_payload = _prepare_contexts(
            frozen=frozen,
            inputs=inputs_path,
            env_file=env_file,
            run_root=run_root,
            temporary_root=Path(temporary).resolve(),
            trace=trace,
        )
    inputs = _load(inputs_path)
    dg10 = {str(record["source_id"]): record for record in dg10_payload["records"]}
    dg11 = {str(record["source_id"]): record for record in dg11_payload["records"]}
    source_ids = {str(value) for value in inputs["source_ids"]}
    if set(dg10) != source_ids or set(dg11) != source_ids:
        raise V2RunError("V2 frozen context source IDs drifted")

    prepared: list[dict[str, Any]] = []
    for case_index, raw in enumerate(inputs["cases"]):
        case = dg11_holdout.product_case(raw)
        lexical_context, lexical_ids, lexical_ms = benchmark._rag_context(case)
        contexts = {
            "CTRL_NO_MEMORY": PrefetchContext.no_memory(),
            "CTRL_CUSTOM_LEXICAL_TOP1": lexical_context,
            "MILAI_DG10_FROZEN": _context(dg10[case.source_case_id]["context"]),
            "MILAI_DG11_FROZEN": _context(dg11[case.source_case_id]["context"]),
        }
        retrieval_ms = {
            "CTRL_NO_MEMORY": 0.0,
            "CTRL_CUSTOM_LEXICAL_TOP1": lexical_ms,
            "MILAI_DG10_FROZEN": _retrieval_ms(dg10[case.source_case_id]),
            "MILAI_DG11_FROZEN": _retrieval_ms(dg11[case.source_case_id]),
        }
        messages = {
            arm: benchmark._messages(case.question, case.question_at, context)
            for arm, context in contexts.items()
        }
        prompt_tokens = {
            arm: benchmark._count_prompt_tokens(endpoint, arm_messages)
            for arm, arm_messages in messages.items()
        }
        no_memory_tokens = prompt_tokens["CTRL_NO_MEMORY"]
        for arm in dg11_v2.schedule(case_index):
            memory_tokens = max(0, prompt_tokens[arm] - no_memory_tokens)
            if memory_tokens > benchmark.MEMORY_TOKEN_BUDGET:
                raise V2RunError(f"V2 memory token ceiling exceeded: {case.source_case_id}")
            prepared.append(
                {
                    "ordinal": len(prepared),
                    "case_index": case_index,
                    "source_id": case.source_case_id,
                    "case_id": case.case_id,
                    "category": case.category,
                    "arm": arm,
                    "schedule": list(dg11_v2.schedule(case_index)),
                    "messages": messages[arm],
                    "prompt_tokens": prompt_tokens[arm],
                    "memory_tokens": memory_tokens,
                    "context": contexts[arm],
                    "retrieval_latency_ms": retrieval_ms[arm],
                    "retrieved_session_ids": (
                        list(lexical_ids)
                        if arm == "CTRL_CUSTOM_LEXICAL_TOP1"
                        else []
                    ),
                }
            )
    if len(prepared) != 400:
        raise V2RunError("V2 prompt preflight denominator is not 400")

    now = datetime.now(UTC)
    provider_manifest = {
        "schema": "milai.provider.closed-test-run.v1",
        "run_id": run_id,
        "phase": "generalization_v2",
        "provider": "local_vllm",
        "endpoint_identity": endpoint,
        "model_id": benchmark.MODEL_ID,
        "dataset_manifest_sha256": dg11_state.sha256(freeze_path),
        "prompt_template_sha256": benchmark.prompt_contract_sha256(),
        "max_native_requests": 400,
        "max_prompt_tokens": 400 * benchmark.PROMPT_TOKEN_BUDGET,
        "max_completion_tokens": 400 * benchmark.MAX_OUTPUT_TOKENS,
        "deadline": (now + timedelta(hours=2)).isoformat(),
        "expires_at": (now + timedelta(hours=3)).isoformat(),
        "synthetic_or_deidentified_only": True,
        "closed_test_access": True,
    }
    manifest_path = run_root / "provider-manifest.json"
    ledger_path = run_root / "provider-ledger.jsonl"
    dg11_state.atomic_json(manifest_path, provider_manifest)
    dg11_state.atomic_json(
        run_root / "benchmark-manifest.json",
        {
            "schema": "milai.dg11.generalization-v2-run-manifest.v1",
            "run_id": run_id,
            "freeze_manifest_sha256": dg11_state.sha256(freeze_path),
            "candidate_id": frozen["candidate_id"],
            "arms": list(dg11_v2.ARMS),
            "case_count": 100,
            "native_answer_requests": 400,
            "answer_workers": ANSWER_WORKERS,
            "labels_opened_before_generation": False,
            "prompt_preflight_count": len(prepared),
        },
    )
    _consume(frozen, run_id, freeze_path)
    gateway = ProviderExecutionGateway(manifest_path, ledger_path)
    transport = JsonCompletionTransport()

    def answer(item: Mapping[str, Any]) -> dict[str, Any]:
        arm = str(item["arm"])
        case_index = int(item["case_index"])
        logical_id = f"{run_id}-{case_index + 1:03d}-{arm.casefold()}"
        call_started = time.perf_counter()
        completion = gateway.execute(
            ProviderRequest(
                logical_request_id=logical_id,
                transport="json",
                payload=benchmark._payload(
                    item["messages"], dg11_v2.generation_id(case_index, arm)
                ),
                prompt_token_budget=benchmark.PROMPT_TOKEN_BUDGET,
                completion_token_budget=benchmark.MAX_OUTPUT_TOKENS,
                timeout_seconds=180,
            ),
            transport,
            benchmark._parse,
        )
        if completion.prompt_tokens != item["prompt_tokens"]:
            raise V2RunError("V2 tokenizer recount differs from native usage")
        context = item["context"]
        assert isinstance(context, PrefetchContext)
        return {
            "ordinal": item["ordinal"],
            "source_id": item["source_id"],
            "case_id": item["case_id"],
            "category": item["category"],
            "arm": arm,
            "schedule": item["schedule"],
            "answer": str(completion.value),
            "answer_sha256": hashlib.sha256(str(completion.value).encode()).hexdigest(),
            "prompt_tokens": completion.prompt_tokens,
            "completion_tokens": completion.completion_tokens,
            "memory_tokens": item["memory_tokens"],
            "memory_context_chars": len(context.rendered),
            "context_sha256": context.context_sha256,
            "retrieval_latency_ms": round(float(item["retrieval_latency_ms"]), 3),
            "retrieved_session_ids": item["retrieved_session_ids"],
            "answer_latency_ms": round((time.perf_counter() - call_started) * 1000, 3),
            "native_request_id": completion.native_request_id,
            "model_calls": 1,
            "hidden_model_calls": 0,
        }

    generation_records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=ANSWER_WORKERS) as executor:
        futures = [executor.submit(answer, item) for item in prepared]
        for future in as_completed(futures):
            generation_records.append(future.result())
            generation_records.sort(key=lambda record: int(record["ordinal"]))
            dg11_state.atomic_json(
                run_root / "sealed-generations.json",
                {
                    "schema": "milai.dg11.generalization-v2-generations.v1",
                    "labels_opened": False,
                    "records": generation_records,
                },
            )
            if len(generation_records) % 10 == 0:
                print(
                    json.dumps(
                        {"phase": "generation", "completed": len(generation_records), "total": 400}
                    ),
                    flush=True,
                )

    events = gateway.read_ledger()
    reservations = [event for event in events if event.get("event") == "RESERVED"]
    terminals = [event for event in events if event.get("event") == "PROVIDER_TERMINAL"]
    post = [event for event in events if event.get("event") == "POST_PROVIDER_TERMINAL"]
    denominator_valid = (
        len(generation_records) == 400
        and len(reservations) == len(terminals) == len(post) == 400
        and all(event.get("status") == "SUCCEEDED" for event in terminals + post)
        and len({event.get("native_request_id") for event in terminals}) == 400
    )
    if not denominator_valid:
        raise V2RunError("V2 provider denominator is incomplete")

    labels = _labels(dataset, source_ids)
    scored = dg11_v2.score_records(generation_records, labels)
    arms = scored["arms"]
    current = arms["MILAI_DG11_FROZEN"]["scorer_v1"]
    dg10 = arms["MILAI_DG10_FROZEN"]["scorer_v1"]
    custom = arms["CTRL_CUSTOM_LEXICAL_TOP1"]["scorer_v1"]
    paired = scored["paired"]["scorer_v1"]
    assistant_delta = dg11_v2.category_delta(
        scored,
        "single-session-assistant",
        "MILAI_DG11_FROZEN",
        "CTRL_CUSTOM_LEXICAL_TOP1",
    )
    preference_delta = dg11_v2.category_delta(
        scored,
        "single-session-preference",
        "MILAI_DG11_FROZEN",
        "CTRL_CUSTOM_LEXICAL_TOP1",
    )
    temporal_delta = dg11_v2.category_delta(
        scored,
        "temporal-reasoning",
        "MILAI_DG11_FROZEN",
        "MILAI_DG10_FROZEN",
    )
    prompt_ratio = round(
        float(current["prompt_tokens_mean"])
        / max(1.0, float(custom["prompt_tokens_mean"])),
        6,
    )
    safety_failures = 0 if _supporting_safety_pass() else 1
    gates = {
        "dg11_minus_dg10_paired_f1_gte_0_04": paired["dg11_minus_dg10_f1_mean"] >= 0.04,
        "dg11_minus_dg10_bootstrap_lower95_gt_zero": paired["bootstrap"]["lower95"] > 0,
        "dg11_minus_dg10_em_gte_zero": (
            float(current["exact_match_mean"]) - float(dg10["exact_match_mean"])
        )
        >= 0,
        "dg11_minus_custom_lexical_f1_gte_0_10": (
            float(current["normalized_f1_mean"])
            - float(custom["normalized_f1_mean"])
        )
        >= 0.10,
        "single_assistant_delta_vs_custom_gte_zero": assistant_delta >= 0,
        "preference_delta_vs_custom_gte_zero": preference_delta >= 0,
        "temporal_delta_vs_dg10_gt_zero": temporal_delta > 0,
        "prompt_token_ratio_vs_custom_lte_1_20": prompt_ratio <= 1.20,
        "safety_failures_zero": safety_failures == 0,
        "provider_denominator_400": denominator_valid,
        "one_answer_call_per_arm_case": all(
            record["model_calls"] == 1 for record in generation_records
        ),
        "hidden_calls_zero": all(
            record["hidden_model_calls"] == 0 for record in generation_records
        ),
    }
    functional_gates = {
        key: gates[key]
        for key in (
            "safety_failures_zero",
            "provider_denominator_400",
            "one_answer_call_per_arm_case",
            "hidden_calls_zero",
        )
    }
    optimized = all(gates.values())
    functional = all(functional_gates.values())
    status = "PASS" if optimized else ("QUALITY_TARGET_NOT_MET" if functional else "FAILED")
    decision = (
        "FUNCTIONAL_OPTIMIZED"
        if optimized
        else ("FUNCTIONAL_QUALITY_TARGET_NOT_MET" if functional else "REVERT_TO_DG10")
    )
    summary = {
        "dg11_minus_dg10_f1": paired["dg11_minus_dg10_f1_mean"],
        "dg11_minus_dg10_bootstrap_lower95": paired["bootstrap"]["lower95"],
        "dg11_minus_dg10_em": round(
            float(current["exact_match_mean"]) - float(dg10["exact_match_mean"]), 6
        ),
        "dg11_minus_custom_lexical_f1": round(
            float(current["normalized_f1_mean"])
            - float(custom["normalized_f1_mean"]),
            6,
        ),
        "single_assistant_delta_vs_custom": assistant_delta,
        "preference_delta_vs_custom": preference_delta,
        "temporal_delta_vs_dg10": temporal_delta,
        "prompt_token_ratio_vs_custom": prompt_ratio,
        "safety_failures": safety_failures,
    }
    result = {
        "schema": "milai.dg11.generalization-v2-result.v1",
        "run_id": run_id,
        "work_package": "DG11-09V2",
        "status": status,
        "decision": decision,
        "candidate_id": frozen["candidate_id"],
        "case_count": 100,
        "provider_requests": 400,
        "hidden_provider_calls": 0,
        "labels_opened_after_generation": True,
        "holdout_reusable": False,
        "development_ai_reviews": 0,
        "aggregates": arms,
        "category_aggregates": scored["categories"],
        "paired": scored["paired"],
        "summary": summary,
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
    dg11_state.atomic_json(run_root / "scored-records.json", scored)
    dg11_state.atomic_json(run_root / "trace.json", {"commands": trace})
    dg11_state.atomic_json(run_root / "result.json", result)
    _record_state(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one-time DG11 generalization V2")
    parser.add_argument(
        "run_id",
        nargs="?",
        default=(
            "dg11-v2-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        ),
    )
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
