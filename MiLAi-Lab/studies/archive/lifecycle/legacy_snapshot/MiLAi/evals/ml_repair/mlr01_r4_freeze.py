"""Freeze ML-R01 R4 data, code, provider, and execution identities."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.dg14.provider import (
    full_provider_contract,
    full_provider_contract_sha256,
)
from evals.ml_repair.mlr01_r4_contract import (
    ANSWER_MAX_TOKENS,
    ANSWER_WORKERS,
    ARMS,
    BENCHMARK_ROOT,
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    CAPABILITY_SEAL_PATH,
    CELL_ROOT,
    CPU_WORKERS,
    DATASET_PATH,
    DENSE_SHARDS,
    EXPECTED_BENCHMARK_COMMIT,
    EXPECTED_DATASET_SHA256,
    EXPECTED_INPUT_SHA256,
    FORMAL_TARGET_COUNTS,
    FULL_CASE_COUNT,
    GLOBAL_ACTIVE_CEILING,
    GOAL_PATH,
    GOAL_SHA256,
    GOAL_VERSION,
    INPUT_PATH,
    JUDGE_MAX_TOKENS,
    JUDGE_WORKERS,
    MEMORY_TOKEN_BUDGET,
    MODEL_ID,
    OFFICIAL_EVALUATOR,
    PRODUCT_ARMS,
    R4_ROOT,
    RETRIEVAL_CASE_COUNT,
    ROOT,
    RUN_ID,
    RUN_ROOT,
    SCHEMA_VERSION,
    STATEFUL_SHARDS,
    TARGET_COUNTS,
    TOKENIZER_PATH,
    VLLM_BASE_URL,
    MLR01R4Error,
    atomic_json,
    canonical_json,
    canonical_sha256,
    capability_seal_digest,
    load_all_cases,
    load_json,
    sha256_file,
    source_order_sha256,
    target_case_ids,
)
from evals.paper.runners.contriever_contexts import (
    CONTRIEVER_SNAPSHOT,
    EXPECTED_TORCH,
    EXPECTED_TRANSFORMERS,
    EXPECTED_WEIGHTS_SHA256,
)
from evals.paper.runners.contriever_contexts import (
    EXPECTED_TOKENIZER_SHA256 as CONTRIEVER_TOKENIZER_SHA256,
)
from evals.paper.runners.contriever_contexts import (
    MODEL_ID as CONTRIEVER_MODEL_ID,
)
from evals.paper.scorers.longmemeval import SCORER_ID

ENV_SPEC_PATH = ROOT / ".aris/compute/ml-r01-r4-local-spec.json"
ENV_LEDGER_PATH = ROOT / ".aris/compute/ml-r01-r4-local.md"
R2_B_PATH = RUN_ROOT / "checkpoints/r2-b-v03/summary.json"
R3_PATH = RUN_ROOT / "checkpoints/r3/progressive-boundary.json"

_IDENTITY_PATHS = (
    "evals/ml_repair/mlr01_r4_contract.py",
    "evals/ml_repair/mlr01_r4_freeze.py",
    "evals/ml_repair/mlr01_r4_contexts.py",
    "evals/ml_repair/mlr01_r4_dense.py",
    "evals/ml_repair/mlr01_r4_providers.py",
    "evals/ml_repair/mlr01_r4_score.py",
    "evals/ml_repair/run_mlr01_r4.py",
    "evals/dg14/provider.py",
    "evals/dg15/contracts.py",
    "evals/dg15/mcp_stdio.py",
    "evals/dg15/runtime_session.py",
    "evals/ml_closure/longmemeval_contexts.py",
    "evals/ml_closure/longmemeval_contract.py",
    "evals/paper/adapters/__init__.py",
    "evals/paper/adapters/baselines.py",
    "evals/paper/datasets/longmemeval.py",
    "evals/paper/runners/contriever_contexts.py",
    "evals/paper/runners/longmemeval.py",
    "evals/paper/scorers/longmemeval.py",
    "integrations/mcp/src/milai_mcp/server.py",
    "runtime/src/milai/application/formation_projection.py",
    "runtime/src/milai/application/formation_recollection.py",
    "runtime/src/milai/application/memory_context.py",
    "runtime/src/milai/application/memory_resolve.py",
    "runtime/src/milai/application/retrieval.py",
)


def _command(*args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(
        list(args), cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _provider_identity() -> dict[str, Any]:
    request = urllib.request.Request(f"{VLLM_BASE_URL}/v1/models", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            value = json.loads(response.read())
    except (OSError, json.JSONDecodeError) as exc:
        raise MLR01R4Error("frozen loopback provider is unavailable") from exc
    models = value.get("data") if isinstance(value, dict) else None
    if not isinstance(models, list) or len(models) != 1:
        raise MLR01R4Error("loopback provider model catalog drifted")
    model = models[0]
    if not isinstance(model, dict) or model.get("id") != MODEL_ID:
        raise MLR01R4Error("loopback provider model identity drifted")
    return {
        "base_url": VLLM_BASE_URL,
        "loopback_only": True,
        "model_id": MODEL_ID,
        "served_model": model,
        "models_response_sha256": canonical_sha256(value),
    }


def _provider_capability_witness() -> dict[str, Any]:
    expected = "MLR01_R4_CAPABILITY_WITNESS"
    payload = {
        "model": MODEL_ID,
        "messages": [
            {
                "role": "user",
                "content": f"Output exactly {expected} and nothing else.",
            }
        ],
        "temperature": 0,
        "top_p": 1,
        "seed": 0,
        "max_tokens": 32,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
        "include_reasoning": False,
    }
    request = urllib.request.Request(
        f"{VLLM_BASE_URL}/v1/chat/completions",
        data=canonical_json(payload),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise MLR01R4Error("local Qwen capability witness failed") from exc
    choices = value.get("choices") if isinstance(value, dict) else None
    content = None
    if (
        isinstance(choices, list)
        and len(choices) == 1
        and isinstance(choices[0], dict)
        and isinstance(choices[0].get("message"), dict)
    ):
        content = choices[0]["message"].get("content")
    if value.get("model") != MODEL_ID or content != expected:
        raise MLR01R4Error("local Qwen capability witness content drifted")
    usage = value.get("usage")
    return {
        "status": "PASS",
        "expected_content_sha256": hashlib.sha256(expected.encode()).hexdigest(),
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "served_model": value.get("model"),
        "prompt_tokens": usage.get("prompt_tokens")
        if isinstance(usage, dict)
        else None,
        "completion_tokens": (
            usage.get("completion_tokens") if isinstance(usage, dict) else None
        ),
        "answer_calls": 0,
        "judge_calls": 0,
        "capability_calls": 1,
        "thinking_enabled": False,
        "max_output_tokens": 32,
        "seed": 0,
    }


def _migration_head() -> str:
    runtime_src = ROOT / "runtime/src"
    if str(runtime_src) not in sys.path:
        sys.path.insert(0, str(runtime_src))
    from alembic.script import ScriptDirectory
    from milai.operations.smoke import _alembic_config

    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    if not isinstance(head, str):
        raise MLR01R4Error("Runtime migration head is ambiguous")
    return head


def _hardware() -> dict[str, Any]:
    gpu_rows = _command(
        "nvidia-smi",
        "--query-gpu=index,name,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    )
    return {
        "logical_cpus": os.cpu_count(),
        "gpu_rows": [row.strip() for row in gpu_rows.splitlines() if row.strip()],
    }


def _validate_entry_gates() -> dict[str, Any]:
    terminal = load_json(RUN_ROOT / "terminal.json")
    results = load_json(RUN_ROOT / "results.json")
    r2_b = load_json(R2_B_PATH)
    r3 = load_json(R3_PATH)
    if (
        not isinstance(terminal, dict)
        or terminal.get("terminal") is not False
        or terminal.get("status") != "ACTIVE_R4"
        or not isinstance(results, dict)
        or results.get("blocks", {})
        .get("R2", {})
        .get("iterations", [])[-1]
        .get("status")
        != "PASS"
        or results.get("blocks", {}).get("R3", {}).get("status") != "PASS"
        or not isinstance(r2_b, dict)
        or r2_b.get("status") != "PASS"
        or not isinstance(r3, dict)
        or r3.get("status") != "PASS"
    ):
        raise MLR01R4Error("R4 entry gates are not complete")
    return {
        "terminal_status": terminal["status"],
        "r2_b_status": r2_b["status"],
        "r2_b_sha256": sha256_file(R2_B_PATH),
        "r3_status": r3["status"],
        "r3_sha256": sha256_file(R3_PATH),
        "r3_strict_accepted_binding_precision": r3["metrics"][
            "StrictAcceptedBindingPrecision"
        ],
        "r3_wrong_complete": r3["metrics"]["WrongCOMPLETE"],
        "r3_correct_case_regression": r3["metrics"]["CorrectCaseRegression"],
    }


def build_capability_seal() -> dict[str, Any]:
    if CAPABILITY_SEAL_PATH.is_file():
        capability_seal_digest()
        value = load_json(CAPABILITY_SEAL_PATH)
        if not isinstance(value, dict):
            raise MLR01R4Error("R4 capability seal is invalid")
        return value
    if CELL_ROOT.exists() and any(CELL_ROOT.rglob("*.json")):
        raise MLR01R4Error("unsealed R4 cells exist before capability freeze")
    if (R4_ROOT / "labels-opened.json").exists():
        raise MLR01R4Error("R4 labels were opened before capability freeze")
    if (
        sha256_file(GOAL_PATH) != GOAL_SHA256
        or sha256_file(INPUT_PATH) != EXPECTED_INPUT_SHA256
        or sha256_file(DATASET_PATH) != EXPECTED_DATASET_SHA256
    ):
        raise MLR01R4Error("ML-R01 goal or LongMemEval data identity drifted")
    benchmark_commit = _command("git", "rev-parse", "HEAD", cwd=BENCHMARK_ROOT)
    benchmark_dirty = _command("git", "status", "--porcelain", cwd=BENCHMARK_ROOT)
    if benchmark_commit != EXPECTED_BENCHMARK_COMMIT or benchmark_dirty:
        raise MLR01R4Error("LongMemEval evaluator checkout identity drifted")
    if not ENV_SPEC_PATH.is_file() or not ENV_LEDGER_PATH.is_file():
        raise MLR01R4Error("R4 environment spec or provider ledger is absent")
    partition, cases = load_all_cases()
    code_sha256: dict[str, str] = {}
    for relative in _IDENTITY_PATHS:
        path = ROOT / relative
        if not path.is_file():
            raise MLR01R4Error(f"R4 identity source is absent: {relative}")
        code_sha256[relative] = sha256_file(path)
    weights = CONTRIEVER_SNAPSHOT / "pytorch_model.bin"
    tokenizer = CONTRIEVER_SNAPSHOT / "tokenizer.json"
    if (
        sha256_file(weights) != EXPECTED_WEIGHTS_SHA256
        or sha256_file(tokenizer) != CONTRIEVER_TOKENIZER_SHA256
    ):
        raise MLR01R4Error("frozen Contriever identity drifted")
    category_counts = Counter(case.category for case in cases)
    entry_gates = _validate_entry_gates()
    provider = _provider_identity()
    witness = _provider_capability_witness()
    material: dict[str, Any] = {
        "schema": f"{SCHEMA_VERSION}.capability-seal",
        "status": "FROZEN",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "goal_version": GOAL_VERSION,
        "goal_sha256": GOAL_SHA256,
        "entry_gates": entry_gates,
        "execution_scope": {
            "current_user_limit": "8_CASES_X_4_ARMS_THEN_STOP",
            "pilot_target_count": 8,
            "formal_target_counts": list(FORMAL_TARGET_COUNTS),
            "formal_targets_authorized_in_current_execution": False,
            "release_decision_authorized_from_pilot": False,
        },
        "source": {
            "benchmark_root": str(BENCHMARK_ROOT),
            "benchmark_commit": benchmark_commit,
            "benchmark_git_clean": True,
            "official_evaluator": str(OFFICIAL_EVALUATOR),
            "official_evaluator_sha256": sha256_file(OFFICIAL_EVALUATOR),
        },
        "data": {
            "classification": "EXTERNAL_PUBLIC_BENCHMARK_NON_HOLDOUT",
            "partition": partition,
            "input_sha256": sha256_file(INPUT_PATH),
            "dataset_sha256": sha256_file(DATASET_PATH),
            "full_case_count": FULL_CASE_COUNT,
            "retrieval_case_count": RETRIEVAL_CASE_COUNT,
            "category_counts": dict(sorted(category_counts.items())),
            "full_source_order_sha256": source_order_sha256(FULL_CASE_COUNT),
            "target_source_order_sha256": {
                str(target): source_order_sha256(target) for target in TARGET_COUNTS
            },
            "pilot_case_ids": list(target_case_ids(8)),
            "pilot_selection": "FIRST_8_IN_FROZEN_LONGMEMEVAL_S_ORDER",
            "label_free_input_contract": True,
            "answer_or_answer_session_fields_accessed": False,
        },
        "arms": {
            "ids": list(ARMS),
            "product": list(PRODUCT_ARMS),
            "MLR01-BM25-T": "OFFICIAL_STYLE_BM25_TURN_EVALUATION_BASELINE",
            "MLR01-DENSE": "FROZEN_FLAT_CONTRIEVER_EVALUATION_BASELINE",
            "MLR01-R": "RAW_PLUS_CANONICAL_SIMPLE",
            "MLR01-F": "FORMED_PLUS_RAW_FALLBACK_PLUS_CANONICAL_SIMPLE",
            "product_raw_and_formed_share_one_ingest_snapshot": True,
            "baseline_canonical_authority": False,
        },
        "configuration": {
            "memory_context_tokens": MEMORY_TOKEN_BUDGET,
            "answer_max_output_tokens": ANSWER_MAX_TOKENS,
            "judge_max_output_tokens": JUDGE_MAX_TOKENS,
            "thinking_enabled": False,
            "answer_workers": ANSWER_WORKERS,
            "judge_workers_separate_window": JUDGE_WORKERS,
            "cpu_workers": CPU_WORKERS,
            "stateful_shards": STATEFUL_SHARDS,
            "dense_shards": DENSE_SHARDS,
            "global_active_ceiling": GLOBAL_ACTIVE_CEILING,
            "logical_attempts_per_cell": 1,
            "automatic_provider_retries": 0,
            "post_result_retuning": False,
        },
        "provider": {
            **provider,
            "contract": full_provider_contract(max_output_tokens=ANSWER_MAX_TOKENS),
            "contract_sha256": full_provider_contract_sha256(
                max_output_tokens=ANSWER_MAX_TOKENS
            ),
            "tokenizer_path": str(TOKENIZER_PATH),
            "tokenizer_sha256": sha256_file(TOKENIZER_PATH),
            "answer_and_judge_windows_overlap": False,
            "openai_or_gpt4o_calls": 0,
            "capability_witness": witness,
        },
        "judge": {
            "prompt": "UPSTREAM_GET_ANSCHECK_PROMPT_AST_EXACT_BODY",
            "official_evaluator_sha256": sha256_file(OFFICIAL_EVALUATOR),
            "temperature": 0,
            "max_output_tokens": JUDGE_MAX_TOKENS,
            "same_model_self_judge_bias_disclosed": True,
        },
        "dense": {
            "model_id": CONTRIEVER_MODEL_ID,
            "snapshot": str(CONTRIEVER_SNAPSHOT),
            "weights_sha256": EXPECTED_WEIGHTS_SHA256,
            "tokenizer_sha256": CONTRIEVER_TOKENIZER_SHA256,
            "torch": EXPECTED_TORCH,
            "transformers": EXPECTED_TRANSFORMERS,
            "gpu_binding": {"0": 2, "1": 3},
        },
        "scoring": {
            "scorer_id": SCORER_ID,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_unit": "question_id",
            "pilot_inference_scope": "DESCRIPTIVE_ONLY_NOT_RELEASE_EVIDENCE",
        },
        "label_boundary": {
            "labels_open_after_target_answers_sealed": True,
            "fields": ["answer", "answer_session_ids"],
            "formal_holdout": False,
            "leaderboard_equivalence_claimed": False,
        },
        "runtime": {
            "migration_head": _migration_head(),
            "database_policy": "FRESH_EPHEMERAL_DATABASE_PER_STATEFUL_SHARD",
            "product_database_mutation": False,
            "environment_spec_sha256": sha256_file(ENV_SPEC_PATH),
            "environment_ledger_sha256": sha256_file(ENV_LEDGER_PATH),
            "hardware": _hardware(),
        },
        "code_sha256": code_sha256,
    }
    value = {**material, "seal_digest": canonical_sha256(material)}
    atomic_json(CAPABILITY_SEAL_PATH, value)
    capability_seal_digest()
    return value


__all__ = ["build_capability_seal"]
